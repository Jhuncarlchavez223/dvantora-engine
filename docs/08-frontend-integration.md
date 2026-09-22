# 08 — Frontend Integration

**Status:** APPROVED — 2026-08-27
**Last updated:** 2026-08-27
**Prerequisite reading:** `01-architecture.md`, `05-api-contract.md`
**Implements:** ADR-0007 (server-rendered app)

Specifies the authenticated app surface: its routes, how a session is established,
how a running analysis is polled, and where the boundary with `/api/v1` sits.

No frontend code exists yet. Nothing here is implemented until approved.

---

## 1. Two surfaces, one process

| Surface | Prefix | Consumer | Returns | Stability |
|---|---|---|---|---|
| App | `/app/*` | The user's browser | HTML, HTMX fragments | Internal — may change freely |
| API | `/api/v1/*` | Automation, service tokens, future clients | JSON | Versioned contract (`05 §10`) |

Both are served by the same FastAPI application at the same origin. `/app/*` is
**not a public interface** and carries no compatibility guarantee; the JSON
contract is where stability lives.

### 1.1 The boundary rule

> App route handlers call the same internal functions the API route handlers call.
> They never reimplement resolution, enqueueing, scoring or report assembly, and
> they never talk to the database in ways the API does not.

This is what keeps ADR-0007's reversal cost honest. If the app needs behaviour the
API does not have, the behaviour is added to the shared layer and both surfaces get
it — not written into a view handler.

Concretely, the shared layer is the existing modules: `markets/resolver.py`,
`pipeline/queue.py`, and the read helpers behind `api/routes/runs.py`. An app route
is a thin call into those plus a template render.

---

## 2. Routes

Four screens, matching the approved product design.

| Method | Path | Screen | Notes |
|---|---|---|---|
| `GET` | `/app` | New analysis | Service + location form |
| `POST` | `/app/runs` | — | Starts a run, redirects to progress |
| `GET` | `/app/runs/{run_id}` | Run progress | Full page; embeds the polled fragment |
| `GET` | `/app/runs/{run_id}/progress` | — | **HTMX fragment**: the stage timeline |
| `GET` | `/app/runs/{run_id}/report` | Report | Score, signals, businesses, analysis |
| `GET` | `/app/markets` | Market list | Past runs, comparable |
| `GET` | `/app/login` | Login | Supabase-hosted or minimal form |
| `POST` | `/app/logout` | — | Clears the session cookie |

`/app/runs/{run_id}/progress` is the only route polled, and the only one returning
a fragment rather than a document.

### 2.1 Ambiguous resolution in the UI

`POST /app/runs` shares the resolver with the API, so it inherits the refusal
behaviour in `05 §5.2`. When resolution is ambiguous or below the confidence
threshold, the form re-renders with the candidate shortlist as selectable options,
and the user's choice re-submits with `market_key`.

The user is never handed a silently guessed market. This is the UI expression of
`02 §3.5`.

---

## 3. Session handling

Supabase issues the session (ADR-0002); the app stores it in a cookie and validates
it **server-side** on every request.

| Property | Value |
|---|---|
| Cookie name | `dv_session` |
| Flags | `HttpOnly`, `Secure`, `SameSite=Lax` |
| Contents | Supabase session token — never account data |
| Validation | One FastAPI dependency, shared with the API's principal resolution |
| Expiry | Supabase session lifetime; refresh handled server-side |

`HttpOnly` means the token is unreachable from JavaScript, which is the main
security gain over the SPA alternative: there is no browser-side token to steal
through an XSS bug.

`SameSite=Lax` is sufficient because the app performs no cross-site form posts.
State-changing routes (`POST /app/runs`, `POST /app/logout`) additionally carry a
CSRF token; HTMX sends it via a request header configured once on `<body>`.

**Unauthenticated requests to `/app/*`** redirect to `/app/login`. Unauthenticated
requests to `/api/v1/*` return `401 unauthenticated` (`05 §1.2`) — the surfaces
differ here deliberately: browsers get redirects, API clients get status codes.

⚠️ The current `api/deps.py` resolves a fixed local account and refuses to run
outside `DVANTORA_ENV=local`. Real session handling replaces it and is gated on
Supabase being adopted, which has not happened yet.

---

## 4. The polling flow

```
POST /app/runs
   └─ resolve market ─▶ freshness check (ADR-0005)
         ├─ fresh run exists ──▶ 303 redirect to /app/runs/{id}/report
         └─ new run queued ────▶ 303 redirect to /app/runs/{id}

GET /app/runs/{id}
   └─ renders the full page, containing:

      <div hx-get="/app/runs/{id}/progress"
           hx-trigger="load, every 3s"
           hx-swap="outerHTML"></div>

GET /app/runs/{id}/progress
   └─ renders the stage timeline fragment
   └─ on a terminal status, the fragment omits hx-trigger and
      emits HX-Redirect to /app/runs/{id}/report
```

### 4.1 Why this shape

- **Polling stops by itself.** The fragment that renders a terminal run simply does
  not include `hx-trigger`, so the loop ends without client-side bookkeeping. This
  is the mechanical advantage over a hand-written SPA poller.
- **The interval matches the API.** `05 §4` sets `poll_after_ms` to 3000 and exempts
  correctly-behaving pollers from rate limiting; the app uses the same cadence.
- **A refresh is free.** State lives in the run row, so reloading mid-run resumes
  polling with no lost context.
- **Redirect on completion** is server-driven via `HX-Redirect`, so the browser
  lands on the report without the fragment needing to know how to render one.

### 4.2 Stage rendering

The fragment renders the same stage list `05 §4` returns: ten stages, each
`pending` / `running` / `ok` / `failed` / `skipped`. A `failed` stage is shown as a
declared gap, not an error state — the run continues and lands in `partial`
(`02 §5`). The timeline mirrors the "how it works" sequence on the marketing site.

---

## 5. Report rendering

The report page renders the payload defined in `05 §6`. Three contract rules matter
to the template and are easy to get wrong:

1. **A signal with `score: null` is rendered, not skipped.** It shows as unavailable
   with its note. Omitting it would breach `00 §7`.
2. **`businesses.sample` may be absent** once the 30-day TTL passes while
   `aggregates` remain (`02 §6`). The template must render a report with no sample
   rows as a normal state, not an error.
3. **`trend.granularity` is always displayed.** A national series labelled as the
   city would breach evidence-first (`07 §7.1`).

`provenance.gates_applied` is surfaced as the plain-language explanation of a capped
verdict, using the same wording the analysis caveats carry (`04 §6`).

`data_age_hours` is shown whenever a report is served from a run inside the
freshness window, so the reader always knows when the evidence was gathered.

---

## 6. Assets and styling

- `main.css` is **copied** from the website repo into `engine/app/static/`, not
  imported across repos. The two surfaces share a design language, not a build.
- Divergence is accepted: the marketing site and the app will drift, and that is
  cheaper than coupling two repos on an asset.
- HTMX is vendored as a single file. No bundler, no `npm`, no lockfile.
- The app degrades without JavaScript for everything except live polling; a run
  page still renders its current state on load.

---

## 7. What the app must never do

- Compute or adjust a score, verdict or confidence — those come from the engine.
- Call a data vendor or a model provider directly.
- Store account data in the cookie beyond the session token.
- Render a number that is not present in the report payload.
- Become a place where business logic accumulates (§1.1).

---

## 8. Open questions

1. **Login mechanism.** Supabase-hosted UI (fastest, off-brand) versus a minimal
   local form posting to Supabase (on-brand, more code). Recommend hosted for the
   MVP.
2. **`app.dvantora.com` routing.** The subdomain points at the engine service; the
   apex stays on the static host. Confirm at deploy time — deployment is not in
   scope yet (ADR-0003).
3. **Empty states.** What the market list shows before a first run, and what the new
   analysis form suggests. Cosmetic, but decide before templates are written.
