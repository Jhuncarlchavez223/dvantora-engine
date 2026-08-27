# 07 — Data Sources

**Status:** DRAFT — awaiting founder approval
**Classification:** INTERNAL. Do not publish. See §11.
**Last updated:** 2026-08-27
**Prerequisite reading:** `00-overview.md`, `01-architecture.md`

This document identifies the real APIs behind each of the six Dvantora signals,
what each costs, what each is allowed to be used for, and exactly what fields
the pipeline extracts. It is the input to `03-research-pipeline.md` and the
basis of the unit economics.

All prices, limits and terms below were checked against vendor documentation on
**2026-08-27**. Each entry carries a verification status. Anything marked
⚠️ NEEDS VERIFICATION must be confirmed before code depends on it.

---

## 1. Summary — recommended MVP stack

| Signal | Primary source | Secondary / cross-check | Est. cost per run |
|---|---|---|---|
| Market demand | DataForSEO — Keywords Data (Google Ads) | Google Ads API direct (later) | $0.06–0.09 |
| Competition | DataForSEO — SERP API (Google Organic + Maps) | — | ~$0.02 |
| Advertising activity | DataForSEO — Ads Transparency + paid slots on the same SERP | ⛔ Meta Ad Library (see §4.3) | ~$0.01 |
| Business density | DataForSEO — Business Data (GBP info) + Maps SERP | ABS Data API (AU, free); OpenStreetMap | ~$0.07 |
| Customer value | CPC from the demand call (free marginal) + Tavily web research | ABS industry turnover (free) | $0.00–0.08 |
| Market trends | DataForSEO — Google Trends / DataForSEO Trends | Google Trends API alpha (waitlisted) | ~$0.02 |
| *(Report prose)* | LLM via provider abstraction | — | ~$0.05 |
| | | **Total per fresh run** | **≈ $0.25–0.40** |

**The single most important architectural consequence:** one vendor
(DataForSEO) covers five of the six signals on a pay-as-you-go basis at a cost
per run measured in cents. That makes the 7-day freshness window comfortable
rather than essential, and it means the collector interface defined in
`01-architecture.md` §1.5 is doing real work — most collectors are thin
wrappers over one vendor, and swapping that vendor is the main portability risk
worth designing against.

---

## 2. Signal 1 — Market demand

### 2.1 DataForSEO — Keywords Data API (Google Ads) — **RECOMMENDED PRIMARY**

| Attribute | Detail |
|---|---|
| **API availability** | Public REST API, immediate signup, no approval process |
| **Pricing** | Standard queue **$0.06/task** (~45 min turnaround); Live mode **$0.09/task** (~7 s) |
| **Rate limits** | Not published as a hard per-minute figure ⚠️ NEEDS VERIFICATION — must be confirmed before setting worker concurrency |
| **Geographic coverage** | Google Ads location targets, including all Australian states, cities and many suburbs |
| **Freshness** | Underlying Google historical metrics **refresh monthly** — a 7-day cache costs nothing in accuracy here |
| **Terms** | Commercial resale permitted under DataForSEO's terms; the vendor carries the relationship with the upstream source |
| **Minimum spend** | Pricing page states a **$50 minimum deposit**; the SERP API page states no deposit and a $1 trial credit ⚠️ CONFLICTING — verify at signup |

**Exact data extracted:**

- `search_volume` — average monthly searches, per keyword
- `monthly_searches[]` — 12-month series (this is the seasonality input, and it
  is the same series the report's "Demand trend · trailing 12 months" chart renders)
- `cpc` — average cost per click (also feeds Signal 5)
- `competition` / `competition_index` — Google's advertiser-competition measure
  (feeds Signal 3, *not* Signal 2 — see §3 note)
- `low_top_of_page_bid` / `high_top_of_page_bid` — bid range (feeds Signal 5)

Query shape: one task per market carrying the full generated keyword set for
that service (core term, emergency/urgent variants, service subtypes,
"near me" and city-qualified forms). Batching keeps this at one task per run.

### 2.2 Google Ads API (direct) — **DEFER TO POST-MVP**

| Attribute | Detail |
|---|---|
| **API availability** | Free, but requires a Google Ads account and an approved developer token |
| **Access levels** | Test (15,000 ops/day, test accounts only) → Explorer (2,880 ops/day, **planning tools restricted**) → Basic (15,000 ops/day, ~5 business day review) → Standard (unlimited, 10 business day review) |
| **Pricing** | $0 for API calls |
| **Rate limits** | Keyword Planning services are **rate limited more aggressively than other services** — explicitly called out in Google's docs |
| **Coverage / freshness** | Same as §2.1 — it is the same upstream data; historical metrics refresh monthly |
| **Terms** | "Keyword research" is a named **permissible use** at Basic access. Standard access additionally imposes Required Minimum Functionality. Explorer access **excludes planning tools**, so Explorer is useless for Dvantora |
| **Restriction to confirm** | Whether presenting this data to non-advertiser end users inside a paid product requires a tool-change application ⚠️ NEEDS VERIFICATION before switching |

**Why defer:** it trades $0.06/run for an approval process, a Google Ads
account, tighter rate limits and an unresolved terms question. Revisit when run
volume makes $0.06 material — roughly 5,000+ runs/month.

---

## 3. Signal 2 — Competition

> **Definitional note:** Google's `competition_index` measures *advertiser*
> competition and belongs to Signal 3. Signal 2 is about how hard the market is
> to win — auction depth *and* organic/local difficulty. Conflating the two
> would double-count the same evidence in the composite score.
> `04-signals-and-scoring.md` must keep them separate.

### 3.1 DataForSEO — SERP API (Google Organic + Google Maps) — **RECOMMENDED PRIMARY**

| Attribute | Detail |
|---|---|
| **API availability** | Public REST API, immediate signup |
| **Pricing** | **$0.0006/SERP** standard (~5 min) · **$0.0012** priority (~1 min) · **$0.002** live (~6 s). Each additional SERP in a batch costs 75% of base |
| **Rate limits** | Not published as a hard figure ⚠️ NEEDS VERIFICATION |
| **Geographic coverage** | Location-coded down to city and postcode level, including Australia |
| **Freshness** | Real-time at fetch |
| **Terms** | DataForSEO operates the collection. Google's own terms prohibit automated querying — using a vendor **transfers** that exposure, it does not eliminate it. This is a deliberate, documented risk acceptance, not an oversight |

**Exact data extracted:**

- Count of distinct root domains in the organic top 10
- Share of top 10 held by **aggregators/directories** (hipages, Yelp, Yellow
  Pages, Airtasker) versus independent local businesses — a high aggregator
  share means organic entry is harder, which is the signal that actually
  matters to a lead-gen operator
- Local pack: number of entries, their rating and review-count distribution
- Paid slots: count of top and bottom ads present (feeds Signal 3 at zero
  marginal cost, since it is the same response)
- SERP feature inventory (local pack, ads, People Also Ask)

Query shape: 3–5 representative keywords per market, live mode for
responsiveness. ≈ $0.006–0.01 per run.

### 3.2 SerpApi — **ALTERNATIVE, NOT RECOMMENDED FOR MVP**

| Attribute | Detail |
|---|---|
| **Pricing** | Free 250 searches/mo · Starter **$25/mo for 1,000** ($0.025/search) · Developer $75/5,000 · Production $150/15,000 |
| **Rate limits** | Throughput 50/hr (free) → 200/hr (Starter) → 1,000/hr (Developer) |
| **Terms** | Markets a "U.S. Legal Shield" — an explicit indemnity posture |
| **Verdict** | ~40× the per-SERP cost of DataForSEO. Worth keeping as a documented fallback if DataForSEO quality or availability disappoints, and worth revisiting purely for its legal posture if that becomes a priority |

---

## 4. Signal 3 — Advertising activity

### 4.1 DataForSEO — Ads Transparency API — **RECOMMENDED PRIMARY**

Two endpoints, both under SERP API pricing:

- `serp/google/ads_advertisers` — which advertisers are active for a term in a location
- `serp/google/ads_search` — the creatives an advertiser is running

| Attribute | Detail |
|---|---|
| **Pricing** | **$0.0006/SERP** standard (40 results) · **$0.0012** priority |
| **Geographic coverage** | Not stated on the pricing page ⚠️ **NEEDS VERIFICATION FOR AUSTRALIA** — this is the highest-priority verification item in this document, because the demo market is Australian |
| **Freshness** | Sourced from Google's Ads Transparency Center, which reflects recently and currently running ads |
| **Terms** | Data originates from a Google transparency product intended for public inspection — a materially better position than scraped ad data |

**Exact data extracted:** advertiser count for the keyword + location; per
advertiser, first/last seen dates and creative count; ad formats in use;
advertiser overlap with the local pack from §3.1 (i.e. are the businesses
ranking organically also the ones advertising?).

### 4.2 Paid slots on the organic SERP — **FREE, ALREADY COLLECTED**

Ad count and advertiser domains come back in the §3.1 response at zero marginal
cost. Across repeated runs of the same market, this becomes a genuine
time-series of auction crowding — one of the few proprietary datasets Dvantora
accumulates simply by operating.

### 4.3 Meta Ad Library API — ⛔ **EXCLUDE FROM MVP**

| Attribute | Detail |
|---|---|
| **API availability** | Free, but requires government-ID identity verification, a developer app, and user tokens that expire ~every 60 days |
| **Coverage — the blocker** | **Commercial ads are returned only for EU and UK audiences** (a Digital Services Act obligation). Political and social-issue ads are worldwide. Outside the EU/UK, commercial ads are visible on the Ad Library *website* but **absent from the API** |
| **Rate limits** | ~200 calls/hour per user token, shared with the general Graph API quota; pagination consumes the budget quickly |
| **Consequence** | For Australian markets — Dvantora's launch geography — this API returns **nothing useful**. Building against it would produce a signal that silently reads zero |

Revisit only if Dvantora expands to EU/UK markets. Until then, Signal 3 rests
on §4.1 and §4.2, and the report must not imply Meta ad activity was checked.

---

## 5. Signal 4 — Business density

### 5.1 ⚠️ Legal constraint that shapes this signal

Google Maps Platform terms are explicit and they directly constrain the data model:

- §3.2.3(a) — *"Customer will not export, extract, or otherwise scrape Google
  Maps Content for use outside the Services… will not copy and save business
  names, addresses, or user reviews."*
- §3.2.3(b) — no caching except as the Service Specific Terms permit.
- Service Specific Terms §14.3 — latitude/longitude may be cached **up to 30
  consecutive days**, then must be deleted.
- General Service Terms §A.3 — **`place_id` may be cached indefinitely.**

**Design rule this forces:**

> Dvantora stores **aggregates permanently** and **per-business rows only
> transiently**. A permanent, growing directory of business names, addresses and
> reviews is not a data model Dvantora may build.

Concretely:

- **Permanent evidence:** business count in the area, rating distribution
  (mean, median, quartiles), review-count percentiles, share advertising,
  share with a website, chain-vs-independent ratio, `place_id` list.
- **Transient (30-day TTL, then purged):** individual names, addresses,
  coordinates, review text.
- The report's "Local businesses · sample view" renders from the transient
  layer while it is live; once purged, the report keeps the aggregates and the
  score, and the sample table is regenerated on the next run. The score never
  depends on data the terms require us to delete.

Using DataForSEO rather than Google's API directly changes who performs the
collection; it does **not** make a permanent business directory a good idea.
The aggregates-first model is the right design under either vendor and is what
`02-data-model.md` should specify.

### 5.2 DataForSEO — Business Data API (Google Business Profile) — **RECOMMENDED PRIMARY**

| Attribute | Detail |
|---|---|
| **Pricing** | Business info **$0.0015/profile** standard (≤45 min) · **$0.003** priority (≤1 min). Reviews **$0.00075 per 10** standard · **$0.0015 per 10** priority |
| **Rate limits** | Not published ⚠️ NEEDS VERIFICATION |
| **Geographic coverage** | Global where Google Business Profiles exist — strong for Australian metro trades |
| **Freshness** | Real-time at fetch; underlying profiles change slowly (weeks/months), so a 7-day cache is generous |

**Extracted:** per profile — rating, review count, category, claimed status,
website present, `place_id`. Aggregated immediately into the permanent
aggregates listed in §5.1. Review *text* is not collected for the MVP; it has a
cost, a storage restriction and no defined role in any of the six signals.

Budget ~20 profiles per market ≈ $0.03–0.06 per run.

### 5.3 ABS Data API — **RECOMMENDED SECONDARY (Australia), FREE**

| Attribute | Detail |
|---|---|
| **API availability** | Free, public, **no API key required** (keys removed Nov 2024) |
| **Format** | SDMX 2.1; XML, JSON or CSV responses |
| **Rate limits** | None published; ABS warns only that performance may degrade under high load |
| **Coverage** | Australia only, by ANZSIC industry × geography |
| **Freshness** | Annual release cadence |
| **Terms** | ABS data is released under Creative Commons Attribution — attribution required, redistribution permitted |
| **Verification** | ⚠️ Confirm *Counts of Australian Businesses (CABEE)* is exposed through the Data API rather than only through Data Explorer |

**Why it matters disproportionately:** this is the only source here that gives a
**true denominator** — actual registered business counts per industry per
region. Everything else counts businesses that chose to appear on Google.
Combined with population, it turns "how many plumbers are on Maps" into
"plumbers per 10,000 residents", which is the honest version of business
density and is defensible to a sceptical client.

### 5.4 OpenStreetMap / Overpass API — **OPTIONAL CROSS-CHECK, FREE**

Free, no key, community rate limits (be polite; heavy use expects a self-hosted
instance). Licensed **ODbL** — attribution *and* share-alike obligations on
derived databases, which is a genuine complication for a commercial product.
Coverage of trade businesses is inconsistent and there are no ratings. Useful
only as a sanity check on counts. **Do not make it load-bearing.**

---

## 6. Signal 5 — Customer value

This is the weakest signal, and the documentation must say so plainly. There is
no API that returns "the average plumbing job in Brisbane is worth $X". Every
approach below is a proxy, and the report must present this signal as an
estimate with its sources attached.

### 6.1 CPC and top-of-page bids — **PRIMARY, ZERO MARGINAL COST**

Already collected in §2.1. Advertisers bid roughly in proportion to what a
conversion is worth, so CPC is the best-correlated observable proxy available.

**Extracted:** `cpc`, `low_top_of_page_bid`, `high_top_of_page_bid`, and the
ratio of CPC to CPC in a reference basket of trades — a relative measure is far
more defensible than an absolute dollar claim.

### 6.2 Tavily (or equivalent) web research — **SECONDARY**

| Attribute | Detail |
|---|---|
| **Pricing** | Free tier **1,000 credits/month**; pay-as-you-go **$0.008/credit**; Project tier 4,000 credits/mo |
| **Coverage / freshness** | Live web, global |
| **Terms** | Standard commercial API terms; content is returned with source URLs, which is what makes it usable as citable evidence |

**Extracted:** published price ranges for the service in the location, each with
its source URL, captured verbatim. The LLM layer summarises but never invents a
figure — a number in the report that is not in the captured evidence is a bug
(`01-architecture.md` §6).

The free tier covers roughly 100 runs/month at ~10 credits each, so this signal
is effectively free at MVP volume.

### 6.3 ABS industry turnover — **TERTIARY, FREE (AU)**

Same API as §5.3. Gives average turnover per business by ANZSIC class, which
brackets plausible job values. Annual freshness; national or state granularity.

### 6.4 Explicitly rejected

- **IBISWorld / market research licences** — high four-figure annual cost, and
  redistribution of their content inside a paid product is not permitted.
- **Scraping consumer price-guide sites** (hipages, Airtasker, Oneflare) — their
  terms prohibit it, and the resulting figures are marketing content, not data.

### 6.5 Honesty requirement

Signal 5 carries a **structurally lower confidence ceiling** than the other
five. `04-signals-and-scoring.md` must cap its confidence accordingly, and the
generated report must describe it as an estimate derived from advertiser bidding
behaviour and published pricing — never as a measured figure. This follows
directly from the content-honesty rules in `00-overview.md` §7.

---

## 7. Signal 6 — Market trends

### 7.1 DataForSEO — Google Trends / DataForSEO Trends — **RECOMMENDED PRIMARY**

| Attribute | Detail |
|---|---|
| **Pricing** | Google Trends: **$0.0027/task** standard · **$0.011** live (~32 s). DataForSEO Trends: Explore **$0.0012** (~2 s) · Subregion/demography **$0.0024** · Merged **$0.006** |
| **Rate limits** | Not published ⚠️ NEEDS VERIFICATION |
| **Geographic coverage** | Country and sub-region. ⚠️ **City-level series for low-volume trade terms are frequently sparse or empty** — a real limitation, not an edge case |
| **Freshness** | Daily to weekly |

**Extracted:** 12-month and 5-year interest series for the core terms;
seasonality index by month; year-over-year slope; rising related queries.

**Granularity fallback rule:** query at the finest available geography; if the
series is sparse or empty, fall back to state, then country, and **record the
geography actually used as part of the evidence**. The report must say which
level the trend was measured at. A trend line silently drawn from national data
while labelled "Brisbane" would breach the evidence-first principle.

### 7.2 Google Trends API (alpha) — **APPLY NOW, DO NOT DEPEND ON**

Closed alpha with a waitlist. Rolling 5-year window; daily/weekly/monthly/yearly
aggregation; country and sub-region; and — importantly — **consistently scaled
values rather than the 0–100 rescaling**, which makes series comparable across
requests and would materially improve cross-market comparison. No published
pricing or quotas.

**Action:** submit an alpha application now, since it costs nothing and the
queue is the long pole. Keep the trends collector behind the standard interface
so adopting it later is a single implementation swap.

### 7.3 pytrends and similar unofficial libraries — ⛔ **EXCLUDE**

Unofficial, frequently broken by upstream changes, and outside Google's terms.
Not acceptable in a product that sells defensible evidence.

---

## 8. Cost model per research run

Assuming a fresh run (cache miss) in live/priority mode for responsiveness:

| Component | Calls | Unit | Cost |
|---|---|---|---|
| Keywords Data (Google Ads), batched | 1 | $0.09 live | $0.090 |
| Organic SERPs | 4 | $0.002 live | $0.008 |
| Maps SERPs | 2 | $0.002 live | $0.004 |
| Ads Transparency | 2 | $0.0012 priority | $0.002 |
| Business profiles | 20 | $0.003 priority | $0.060 |
| Google Trends | 2 | $0.011 live | $0.022 |
| Tavily web research | ~10 credits | $0.008 | $0.080 (free tier: $0) |
| LLM analysis | 1 | ~15k in / 2k out | $0.050 |
| **Total** | | | **≈ $0.32** |

Standard-queue mode instead of live drops the data cost to roughly **$0.12**,
at the price of a slower run. Since the product's own illustrative timeline
implies ~11 minutes end to end, **standard queue is compatible with the promised
experience** — a decision for `03-research-pipeline.md`.

With a 7-day freshness window, cost scales with *distinct markets researched*,
not with users or page views. At 500 fresh runs/month the data bill is
**≈ $160/mo live, ≈ $60/mo standard**, against the ~$80/mo fixed infrastructure
from `01-architecture.md`.

**Per-run budget ceiling:** set a hard cap of **$0.75** per run in
configuration. Any run exceeding it stops collecting and scores what it has,
with reduced confidence. This makes a runaway collector a degraded report
rather than an invoice.

---

## 9. Rate limits and concurrency

Every DataForSEO rate limit in this document is ⚠️ unverified. Until they are
confirmed, the pipeline must assume it can be throttled at any time:

- Every collector implements exponential backoff with jitter on 429/5xx.
- A global per-vendor concurrency semaphore, set from configuration, not from
  the number of worker processes.
- A failed collector degrades its signal's confidence; it never fails the run
  (`01-architecture.md` §5).
- Vendor errors are recorded as evidence-of-absence so the report can state
  which signals were unavailable.

**Verification task before implementation:** confirm published rate limits and
concurrency allowances for each DataForSEO endpoint family, and record them here.

---

## 10. Terms and compliance summary

| Source | Commercial use | Storage constraint | Attribution | Residual risk |
|---|---|---|---|---|
| DataForSEO | Permitted | None imposed by vendor | None | Upstream collection exposure sits with vendor — **not eliminated** |
| Google Ads API (direct) | Keyword research is a named permissible use | — | — | Displaying to non-advertisers ⚠️ unverified |
| Google Maps / Places (direct) | Restricted | 30-day cache; `place_id` indefinite; **no saving of names, addresses, reviews** | Google Maps attribution | High — drives the aggregates-only model in §5.1 |
| Google Ads Transparency | Public transparency data | None specific | — | Low |
| Meta Ad Library | Free | — | — | Excluded: no commercial coverage outside EU/UK |
| ABS Data API | Permitted | None | **CC-BY attribution required** | Very low |
| OpenStreetMap | Permitted | — | **ODbL: attribution + share-alike on derived DBs** | Licence contamination if load-bearing |
| Tavily | Permitted | — | Cite source URLs | Low |

### Standing rules

1. No permanent database of business names, addresses or reviews derived from
   Google. Aggregates permanently; identity transiently, with a 30-day TTL.
2. No republishing of raw third-party data as a product. Dvantora sells
   analysis, not data access — consistent with `00-overview.md` §5.
3. No scraping behind logins or paywalls; no circumvention of robots.txt in any
   first-party collector.
4. Every vendor sits behind a collector interface, with the vendor name and
   fetch timestamp stored on every evidence row, so any figure in any report can
   be traced to its origin.
5. If ABS or OpenStreetMap data reaches a user-visible surface, the required
   attribution ships with it.

---

## 11. Publication warning

This document contains vendor pricing, cost-per-run economics and source
strategy. It lives in the **private `dvantora-engine` repository** (ADR-0001)
and must stay there: it was never published, and it must not be copied into the
website repository, which deploys from its root with `robots.txt` allowing all
crawlers. The website repo's `.gitignore` excludes `docs/` as a guard against
accidental re-introduction. Keep this classification if the file is ever
excerpted elsewhere.

---

## 12. Verification tasks before implementation

| # | Item | Why it blocks |
|---|---|---|
| 1 | **Ads Transparency coverage for Australia** | If AU is not covered, Signal 3 has no primary source and the design changes |
| 2 | DataForSEO rate limits per endpoint family | Sets worker concurrency and run wall-clock time |
| 3 | DataForSEO minimum deposit ($50 vs $1 trial — sources conflict) | Trivial, but affects when you can start testing |
| 4 | ABS CABEE availability via the Data API | Determines whether the per-capita density denominator is automatable |
| 5 | Google Trends city-level availability for AU trade terms | Determines whether the fallback rule in §7.1 is the common path or the rare one |
| 6 | Google Ads API terms re: display to non-advertisers | Only blocks the post-MVP migration in §2.2 |
| 7 | Google Trends API alpha application submitted | Free; long queue; do it now |

Items 1–5 should be settled with a paid trial account and a handful of live
calls against *Plumbing — Brisbane, QLD* before `03-research-pipeline.md` is
finalised. That single afternoon of verification de-risks the whole pipeline.
