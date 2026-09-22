# 04 — Signals and Scoring

**Status:** APPROVED (v1.0 starting priors) — 2026-08-27
**Prerequisite reading:** `00-overview.md`, `02-data-model.md`, `07-data-sources.md`
**Implements:** `weights_version = "1.0"`, `method_version = "1.0"`

This document defines how evidence becomes a number. It is the product.

> **Everything here is a versioned starting prior, not a measurement.** The weights,
> the curves, the thresholds and the gates were reasoned from Dvantora's economics,
> not fitted to data. They are to be **recalibrated after the first ~30 real market
> runs**. `weights_version` and `method_version` are stamped on every score and
> report so a recalibration never silently changes the meaning of a past result.

---

## 1. The two-stage shape

```
evidence ──normalise──> six sub-scores (0-100, each with confidence)
                              │
                              ├──weighted combine──> opportunity_score (0-100)
                              │
                              └──gates──────────────> verdict (pursue/watch/pass)
```

**Gates cap the verdict. They never change the score.** A market with a good number
and a disqualifying weakness keeps its number and loses its recommendation. This
keeps the score honest and the advice conservative, and it lets the report say
exactly why the recommendation was held back.

---

## 2. Weights

| Signal | Weight | Rationale |
|---|---:|---|
| Demand | **0.25** | The ceiling on everything else. A market nobody searches for cannot be rescued by margins or weak competition. |
| Competition | **0.20** | The cost side. Auction depth and aggregator dominance decide whether entry is affordable at all. |
| Customer value | **0.20** | The other half of unit economics. A high-value job market at moderate volume beats a low-value one at high volume. |
| Business density | **0.15** | For a lead-generation operator this is the buyer pool — who will actually pay for the leads. Also the best-measured signal. |
| Advertising activity | **0.10** | Most of its information is already carried by Competition (auction depth) and Customer value (CPC). Weighting it higher double-counts the same evidence. Its unique contribution is momentum. |
| Trends | **0.10** | Direction, not size. A modifier on the others. |

Sums to 1.00.

## 3. The formula

Each signal contributes in proportion to **importance × confidence**:

```
available = signals with a non-null sub-score

evidence_weight   = Σ_available (wᵢ × cᵢ)
opportunity_score = Σ_available (wᵢ × cᵢ × sᵢ) / evidence_weight

coverage   = Σ_available wᵢ / Σ_all wᵢ
confidence = evidence_weight / Σ_all wᵢ
```

Weighting by confidence as well as importance is deliberate. Customer value carries
0.20 of the score on the weakest evidence in the system — `07 §6.5` caps its
confidence at 0.45 because it is a proxy, not a measurement. Confidence-weighting
means thin evidence automatically contributes less, instead of the weight being
fudged downward to compensate. The weights then mean what they say.

Renormalising over available signals means a missing signal lowers `coverage` and
`confidence` without dragging the score toward zero.

**Insufficient evidence.** If `coverage < 0.5` the run does not score at all: status
`failed`, no `scores` row, no invented number (`00 §5`).

---

## 4. Normalisation curves

All curves output 0–100 where **higher is more attractive to the buyer**. This
inverts the plain-language sense of one signal: a high *Competition* sub-score means
competition is *weak*, and report wording must reflect that.

### 4.1 Demand — logarithmic, monotonic

```
score = 100 × ln(searches / 100) / ln(50000 / 100),  clamped 0-100
```

Search volume is not linear in value: the step from 100 to 1,000 monthly searches
changes the business far more than 10,000 to 10,900. Floor 100 (below this a market
is not addressable), ceiling 50,000 (a metro-scale trade term).

Confidence 0.90 — the best-measured signal.

### 4.2 Competition — monotonic, higher = easier to enter

```
difficulty = 0.50 × aggregator_share
           + 0.30 × min(paid_slots, 4) / 4
           + 0.20 × domain_concentration      where domain_concentration = 1 − distinct_domains/10
score      = 100 − 100 × difficulty
```

Aggregator share carries the most weight because directory dominance is the barrier
money cannot easily solve — outranking a national directory is a different problem
from outbidding a competitor. Paid slots proxy auction depth. Domain concentration
catches a top-10 owned by a few players.

Confidence 0.75.

### 4.3 Advertising activity — inverted U

```
p     = ln(count + 1) / ln(61)                  position on a log scale, 0-1
base  = 100 × (1 − ((p − 0.55) / 0.55)²)        peak at p = 0.55
score = clamp(base + clamp(growth_90d × 100, −15, +15))
```

**This is the signal most often modelled wrongly.** Zero advertisers is not a free
win — it usually means the market does not monetise. A saturated field monetises but
is expensive. The attractive position is a healthy, active, not-yet-crowded market,
so the curve peaks in the middle and falls away at both ends.

The momentum term (±15) is advertising's unique contribution: a market whose
advertiser count is rising is being validated by people spending their own money.

Band: `growing` if growth > 0.05, `declining` if < −0.05, otherwise by score.
Confidence 0.70.

### 4.4 Business density — saturating, rise then plateau

```
per_10k  = business_count / population × 10000    when population is known
score    = 100 × per_10k / (per_10k + 0.5)        saturating
fallback = 100 × ln(count / 5) / ln(400 / 5)      when population is unknown
```

Very few businesses means nobody to sell leads to. Past a point, more businesses stop
adding value — hence saturation rather than unbounded growth.

⚠️ `business_count` from map listings is a **sample, not a census**: results are
capped and include only businesses that chose to appear. Per-capita figures derived
from it are indicative. The true denominator is official business counts
(`07 §5.3`); until that is wired in, both paths record which was used in `inputs`
and say so in `notes`.

Confidence 0.80 with population, 0.65 without — the fallback is less comparable
across markets.

### 4.5 Customer value — logarithmic ratio, bounded

```
ratio = cpc / cpc_basket_median
score = clamp(50 + 35 × log₂(ratio))
```

Advertisers bid roughly in proportion to what a conversion is worth, so CPC relative
to a reference basket of trades is the best-correlated observable proxy. A *relative*
measure is far more defensible than an absolute dollar claim. Logarithmic and bounded
so one outlier CPC cannot saturate the signal.

**Confidence is capped at 0.45** (`07 §6.5`). This signal has a structurally lower
ceiling than the other five and must be described in reports as an estimate derived
from bidding behaviour and published pricing — never as a measured figure.

#### Reference basket — v1 (approved 2026-09-23)

The live source is Google Ads Keyword Planner historical metrics
(`engine/collectors/google_ads_value.py`). `cpc` and `cpc_basket_median` are both
Google's 12-month **average cost per click**, in the market's own location.

**Basket v1** — 12 local, hands-on trades bought by the same kind of customer,
spanning low- to high-value jobs:

> electrician · plumber · carpenter · painter · roofer · landscaper ·
> house cleaning · pest control · locksmith · air conditioning repair ·
> concreter · tiler

**Rules**

1. The trade and the whole basket are priced in **one** Google Ads request.
2. The trade is **removed from its own basket**, so it is compared only with
   other trades.
3. The **median** is used, not the mean, so one inflated trade (for example
   locksmith emergency call-outs) cannot skew the reference.
4. At least **8** basket trades must return a price above zero; otherwise the
   signal is **unavailable** rather than a thin estimate.
5. Every evidence row stores `basket_version`, each basket trade's price, and the
   number priced. Changing the basket means a new version (`v2`), so old reports
   always show which basket produced them.

**First live observation — Plumbing, Brisbane (2026-09-23).** Plumber CPC
$52.48 AUD against a basket median of $13.63 (11 of 11 priced; median trade:
concreter), a ratio of 3.85×. That is the highest price in the basket and scores
**100** after clamping — the raw formula gives about 118. The signal is working
as designed, but a score pinned at the ceiling cannot separate "expensive" from
"extremely expensive". Record this for the §8 recalibration review; the curve is
**not** changed here.

**Candidate for v2:** "painter" returned only $2.11, likely because the single
word also matches art-related searches. A more specific keyword such as
"house painter" would be cleaner. It barely moved the v1 median.

### 4.6 Trends — linear on slope, granularity-penalised

```
score = clamp(50 + yoy_slope × 200)
```

50 is flat. A ±0.25 annual slope reaches the bounds.

Band: `growing` if slope > 0.03, `declining` if < −0.03, else `moderate`.

**Granularity penalty.** Trend series for low-volume local terms are often sparse at
city level (`07 §7.1`). When the series was measured at a coarser geography than the
market, confidence is reduced and the fact is recorded:

| Measured at | Confidence multiplier |
|---|---|
| city / suburb (matches market) | 1.00 |
| admin1 (state) | 0.80 |
| country | 0.60 |

Base confidence 0.70. A trend drawn from national data and labelled as the city would
breach evidence-first, so `notes` always states the geography used.

---

## 5. Thresholds

| Verdict | Score |
|---|---|
| **Pursue** | ≥ 70 |
| **Watch** | 45 – 69 |
| **Pass** | < 45 |

A calibration starting point. The real test is the **base rate**: Pursue should be
uncommon — roughly 15–25% of markets researched. If early real runs return Pursue far
more often, the bar is too low and moves in `weights_version 1.1`.

---

## 6. Gates

Gates only ever **lower** a verdict. Every gate that fires is recorded on the score
and surfaced in the report, so the reasoning is visible.

| # | Gate | Condition | Effect |
|---|---|---|---|
| **G1** | Demand floor | demand sub-score < 30 | cap at Watch |
| | | demand sub-score < 15 | force Pass |
| **G2** | Confidence gate | overall confidence < 0.50 | cap at Watch |
| **G3** | Monetisation evidence | **both** advertising **and** customer value are materially absent | cap at Watch |
| **G4** | Decline guard | trends band is `declining` | cap at Watch |

**G1** — no volume, no business. Below the lower floor the market is not addressable
and the number must not be allowed to imply otherwise.

**G2** — a "Pursue" issued on thin evidence contradicts evidence-first (`00 §6`).
This gate can fire on full coverage with uniformly weak confidence, which is exactly
the case it exists for.

**G3 — an evidence-presence gate, not a numeric one.** Advertising activity and
customer value are the two signals that speak to whether a market *monetises*. If
neither produced usable evidence, the run has no basis for recommending spend,
however good demand and density look. It is deliberately defined on the **absence of
evidence** — no thresholds on advertiser counts or CPC values — because any numeric
cutoff here would be invented rather than derived. Once real runs exist, a calibrated
numeric condition may be added in a later version.

**G4** — a healthy snapshot of a shrinking market is a trap. Today's numbers describe
a position that is eroding.

---

## 7. What is stored

| Field | Where | Purpose |
|---|---|---|
| `score`, `confidence`, `band`, `inputs`, `notes` | `signals` | Per-signal detail the report renders |
| `method_version` | `signals` | Which curves produced it |
| `opportunity_score`, `verdict`, `confidence` | `scores` | The headline |
| `weights_version` | `scores` | Which weights, thresholds and gates applied |
| `gates_applied`, `coverage` | report `provenance` | Why the verdict was capped |

`gates_applied` is an additive field on the report payload; `05 §10` permits new
response fields inside v1 and requires clients to ignore unknown ones.

---

## 8. Recalibration protocol

After ~30 real market runs:

1. Check the Pursue base rate against the 15–25% target.
2. Check whether any sub-score is effectively constant across markets — a signal that
   never varies is carrying weight it does not earn.
3. Check how often each gate fires. A gate that never fires is untested; one that
   fires on most runs is doing the thresholds' job and belongs in the curve instead.
4. Re-derive, bump `weights_version` to `1.1`, leave existing reports stamped `1.0`.
   Do not re-score historical runs silently.
