# 05 — API Contract

**Status:** APPROVED — 2026-08-27
**Last updated:** 2026-08-27
**Prerequisite reading:** `01-architecture.md`, `02-data-model.md`
**Implements:** ADR-0002 (Supabase JWT), ADR-0005 (freshness), ADR-0006 (n8n via public API only)

This is the contract the product UI is coded against and the only coupling
between the two repositories. It is also the single interface n8n or any other
automation may use — there is no private back channel and no direct database
access (ADR-0006).

---

## 1. Conventions

| | |
|---|---|
| **Base URL** | `https://app.dvantora.com/api/v1` (same origin as the app — ADR-0007) |
| **Content type** | `application/json; charset=utf-8` |
| **Auth** | `Authorization: Bearer <supabase-jwt>` |
| **Time** | RFC 3339, always UTC, always `Z` |
| **IDs** | UUID v4 as strings |
| **Casing** | `snake_case` in all payloads |
| **Money** | Integer cents in a named field (`spend_cents`), never floats |

### 1.1 Principals

| Principal | Token | Can do |
|---|---|---|
| User | Supabase JWT | Everything scoped to their own account |
| Service | Static service token, `Authorization: Bearer svc_…` | Create runs, read any run. Used by automation |
| Anonymous | none | `/health` only |

A service token is **not** an admin token. It acts on behalf of a named account
supplied in `X-On-Behalf-Of`, so scheduled runs are attributable to a real
account and the same quota applies.

### 1.2 Errors

```json
{
  "error": {
    "code": "market_ambiguous",
    "message": "That location matched more than one market.",
    "details": { "candidates": [ … ] }
  }
}
```

`code` is stable and machine-readable; `message` is human-readable and may
change. Clients switch on `code`, never on `message`.

| HTTP | `code` | Meaning |
|---|---|---|
| 400 | `invalid_request` | Malformed body or params |
| 401 | `unauthenticated` | Missing/invalid token |
| 403 | `forbidden` | Valid token, not your resource |
| 403 | `access_tier_disabled` | Account disabled |
| 404 | `not_found` | |
| 409 | `market_ambiguous` | Resolution below confidence threshold — see §5.2 |
| 409 | `run_in_progress` | A run for this market is already active |
| 422 | `service_unknown` | Service not in the taxonomy |
| 422 | `location_unknown` | Location could not be resolved |
| 429 | `quota_exceeded` | Monthly run quota spent |
| 429 | `rate_limited` | Too many requests; `Retry-After` set |
| 503 | `capacity` | Queue depth ceiling reached |

---

## 2. Endpoint summary

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness. Unauthenticated |
| `GET` | `/services` | The service taxonomy, for the input's autocomplete |
| `POST` | `/markets/resolve` | Preview canonical resolution without starting a run |
| `POST` | `/runs` | Start (or reuse) a research run |
| `GET` | `/runs` | List the caller's runs |
| `GET` | `/runs/{run_id}` | Status and stage progress — the polling endpoint |
| `GET` | `/runs/{run_id}/report` | The completed report |
| `GET` | `/runs/{run_id}/evidence` | Evidence behind the report |
| `POST` | `/runs/{run_id}/cancel` | Cancel a queued or running run |
| `GET` | `/markets/{market_key}/runs` | History for one market |

MVP scope only. No bulk endpoints, no public third-party API
(`00-overview.md` §5).

---

## 3. `POST /runs`

The one endpoint that matters. It encodes ADR-0005.

**Request**

```json
{
  "service": "Plumbing",
  "location": "Brisbane, QLD",
  "force_refresh": false
}
```

`service` and `location` are free text as typed by the user. Resolution is the
server's job — a client must never be expected to know `market_key`.

Optionally, a caller that has already resolved may send `market_key` instead of
the two free-text fields.

**Response — new run queued: `202 Accepted`**

```json
{
  "run_id": "9c1f…",
  "status": "queued",
  "reused": false,
  "market": {
    "market_key": "plumbing@au-qld-brisbane",
    "service": { "slug": "plumbing", "display_name": "Plumbing" },
    "location": { "slug": "au-qld-brisbane", "display_name": "Brisbane, QLD", "granularity": "city" },
    "resolution": { "method": "alias", "confidence": 0.97 }
  },
  "poll_after_ms": 3000
}
```

**Response — existing fresh run reused: `200 OK`**

```json
{
  "run_id": "4b8e…",
  "status": "complete",
  "reused": true,
  "data_age_hours": 52,
  "freshness_window_hours": 168,
  "market": { … },
  "report_url": "/api/v1/runs/4b8e…/report"
}
```

`reused: true` is not an optimisation detail to hide — the UI must show the data
age, because a report's honesty depends on the reader knowing when it was
gathered (`00-overview.md` §6, evidence first).

`force_refresh: true` bypasses the window and always creates a new run,
subject to quota.

**Response — ambiguous: `409`** — see §5.2.

### 3.1 Idempotency

Clients may send `Idempotency-Key`. Within 24 hours the same key returns the
same `run_id` rather than creating a second run. Without a key, the freshness
window already prevents most duplicates; the header covers double-submits inside
the window of a run that is still `queued`.

---

## 4. `GET /runs/{run_id}` — the polling endpoint

Called roughly every 3 seconds while a run is active (`01-architecture.md` §8).

```json
{
  "run_id": "9c1f…",
  "status": "collecting",
  "current_stage": "collect_density",
  "market": { … },
  "requested_at": "2026-08-27T04:02:11Z",
  "started_at": "2026-08-27T04:02:14Z",
  "completed_at": null,
  "progress": { "completed": 4, "total": 10 },
  "stages": [
    { "stage": "resolve",             "status": "ok",      "started_at": "…", "finished_at": "…" },
    { "stage": "collect_demand",      "status": "ok",      "started_at": "…", "finished_at": "…" },
    { "stage": "collect_competition", "status": "ok",      "started_at": "…", "finished_at": "…" },
    { "stage": "collect_advertising", "status": "failed",  "error_code": "vendor_unavailable" },
    { "stage": "collect_density",     "status": "running", "started_at": "…" },
    { "stage": "collect_value",       "status": "pending" },
    { "stage": "collect_trends",      "status": "pending" },
    { "stage": "score",               "status": "pending" },
    { "stage": "analyze",             "status": "pending" },
    { "stage": "finalize",            "status": "pending" }
  ],
  "poll_after_ms": 3000
}
```

The `stages` array is the timeline the product UI already visualises — it maps
one-to-one onto the site's "how it works" sequence. **A failed stage does not
end the run**; the run continues and lands in `partial` (`02-data-model.md` §5).

Terminal statuses: `complete`, `partial`, `failed`, `cancelled`. On terminal,
`poll_after_ms` is `null` and the client stops.

`ETag` is set; clients should send `If-None-Match` and handle `304`.

---

## 5. Market resolution

### 5.1 `POST /markets/resolve`

Same body as `POST /runs`, no side effects. Lets the UI confirm what will be
analysed before spending a run.

```json
{ "resolved": true, "market": { … }, "alternatives": [ … ] }
```

### 5.2 Ambiguity — `409 market_ambiguous`

When confidence is below the configured threshold, the server does **not**
guess:

```json
{
  "error": {
    "code": "market_ambiguous",
    "message": "That location matched more than one market.",
    "details": {
      "candidates": [
        { "market_key": "plumbing@au-qld-brisbane", "display_name": "Plumbing — Brisbane, QLD", "confidence": 0.62 },
        { "market_key": "plumbing@au-nsw-brisbane-water", "display_name": "Plumbing — Brisbane Water, NSW", "confidence": 0.55 }
      ]
    }
  }
}
```

The client presents the choice and re-submits with `market_key`. This is the
API-level expression of the warning in `02-data-model.md` §3.5: a confident
report about the wrong market is the worst failure mode this product has.

---

## 6. `GET /runs/{run_id}/report`

Available when status is `complete` or `partial`; `409 report_not_ready`
otherwise.

```json
{
  "run_id": "9c1f…",
  "market": { … },
  "generated_at": "2026-08-27T04:13:52Z",
  "data_age_hours": 0,
  "score": { "opportunity_score": 74.5, "verdict": "pursue", "confidence": 0.78 },
  "signals": [
    {
      "signal": "demand",
      "score": 81.0,
      "band": "high",
      "confidence": 0.9,
      "headline": "Recurring, urgent service demand",
      "inputs": { "monthly_searches": 8100, "seasonality_index": 0.22 },
      "notes": null
    },
    {
      "signal": "advertising",
      "score": null,
      "band": "unknown",
      "confidence": 0.0,
      "headline": "Advertising activity unavailable",
      "inputs": {},
      "notes": "Source unavailable during this run; excluded from the score."
    }
  ],
  "trend": {
    "granularity": "admin1",
    "note": "Measured at state level; city-level series was unavailable.",
    "series": [ { "period": "2025-09", "value": 68 }, … ]
  },
  "businesses": {
    "available": true,
    "expires_at": "2026-09-26T04:13:52Z",
    "aggregates": { "count": 128, "rating_mean": 4.4, "review_count_median": 61, "share_advertising": 0.28 },
    "sample": [ { "name": "…", "rating": 4.8, "review_count": 210, "advertising": true } ]
  },
  "analysis": {
    "generator": "llm",
    "summary": "…",
    "reasons": [ { "n": 1, "title": "Recurring, urgent demand", "body": "…" } ],
    "recommended_action": "…",
    "caveats": [ "Advertising activity could not be collected for this run." ]
  },
  "provenance": {
    "weights_version": "2026.08-1",
    "prompt_version": null,
    "provider": null,
    "model": null,
    "sources": [ { "signal": "demand", "vendor": "…", "fetched_at": "…" } ]
  }
}
```

### 6.1 Contract rules the client can rely on

1. **A missing signal is present with `score: null` and a `note`** — never
   silently omitted. This is `00-overview.md` §7 expressed in JSON.
2. **`businesses.sample` may disappear.** Once `expires_at` passes, `available`
   becomes `false` and `sample` is absent while `aggregates` remain. The UI must
   render the report correctly with no sample rows — the 30-day purge in
   `02-data-model.md` §6 makes this a normal state, not an error.
3. **`trend.granularity` is always stated.** A trend measured at state level and
   labelled as the city would breach evidence-first (`07-data-sources.md` §7.1).
4. **`provenance` is mandatory.** Every report can be traced to its weights,
   prompt and sources.
5. **`analysis.generator` may be `template`.** Clients must render it the same
   way; it is a valid state, not a degraded one (ADR-0004).

---

## 7. `GET /runs/{run_id}/evidence`

Paginated, filterable by `?signal=`. Returns evidence rows with `vendor`,
`endpoint`, `status`, `fetched_at`, `source_url` and the normalised `payload`.

Powers the "show me why" affordance behind every claim. Rows whose
`expires_at` has passed are gone; the response states the count purged rather
than pretending they never existed.

---

## 8. `GET /runs` and `GET /markets/{market_key}/runs`

Cursor-paginated:

```json
{ "items": [ … ], "next_cursor": "eyJ…", "has_more": true }
```

Offset pagination is not used — the list is ordered by `requested_at DESC` and
grows at the head.

Each item carries `run_id`, `market`, `status`, `opportunity_score`, `verdict`,
`completed_at`, `data_age_hours` — enough to render the comparison list in
`00-overview.md` §5 item 6 without a second call per row.

---

## 9. Rate limiting and quota

| Limit | Scope | Response |
|---|---|---|
| 60 requests/minute | Per token | `429 rate_limited`, `Retry-After` |
| 1 active run per market | Global | `409 run_in_progress` |
| `run_quota_month` | Per account | `429 quota_exceeded` |
| Queue depth ceiling | Global | `503 capacity` |

Polling is exempt from the per-minute limit up to one request per 2 seconds per
run, so a client following `poll_after_ms` is never rate-limited for behaving
correctly.

---

## 10. Versioning

- The path carries the major version. `v1` is additive-only: new optional
  request fields and new response fields may appear at any time; clients must
  ignore unknown fields.
- Removing a field, renaming one, or changing a type requires `v2`.
- Error `code` values are additive; clients must treat unknown codes as generic
  failures rather than crashing.

---

## 11. Open questions

1. ~~**`api.dvantora.com` vs `app.dvantora.com/api`**~~ — **RESOLVED (ADR-0007).**
   The app is server-rendered by the same FastAPI application, so the API is
   served **same-origin** at `app.dvantora.com/api/v1`. No CORS configuration, no
   preflight, no cross-origin token handling. `api.dvantora.com` may later be
   added as an alias for automation clients; if it is, CORS becomes a live concern
   again and this section must be revisited.
2. **Evidence exposure.** §7 shows normalised vendor payloads to users. Confirm
   this is acceptable against vendor terms before it ships; the safer default is
   to expose provenance metadata without the payload body.
3. **Report payload versioning.** Should `reports.payload` carry its own
   `schema_version` so old reports render in a newer UI? Recommended yes; decide
   before the first report is stored.
