# 00 — Product Overview

**Status:** DRAFT — awaiting founder approval
**Related decisions:** `adr/0001`–`adr/0006` accepted 2026-08-27
**Owner:** Dvantora (solo founder)
**Last updated:** 2026-08-27

This document is the entry point to the Dvantora specification. Everything in
`/docs` is authoritative: code follows the docs, not the other way around. When
an implementation detail contradicts a doc, either the code is wrong or the doc
needs an explicit, approved change.

---

## 1. What Dvantora is

Dvantora is an AI-powered local market and advertising intelligence platform.

A user enters **one service and one location** — for example *Plumbing —
Brisbane, QLD*. Dvantora then researches that market automatically across
demand, competition, advertising activity, local business density, customer
value and trends, weighs the evidence, and produces:

- an **opportunity score** (0–100),
- a **verdict** — Pursue / Watch / Pass,
- a **written analysis** in plain language, and
- an **evidence-backed report** the user can act on or hand to a client.

The product is not a data export. It is an answer to a business question:
*is this market worth my budget, and why?*

## 2. The unit of analysis

> **One market = one service × one location.**

This is the single most important modelling decision in the product. Every
signal, score, report, cache entry and database row hangs off it. National
averages are explicitly not the product; the whole value is local specificity.

- **Service** — a normalised trade or service category (`plumbing`,
  `emergency-plumbing`, `hvac-repair`).
- **Location** — a normalised geography with an explicit granularity
  (city, region, suburb) and country.

Market identity must be *canonical*: "Plumbing, Brisbane", "plumber brisbane
qld" and "Plumbing — Brisbane, QLD" are the same market and must resolve to the
same record, or caching, comparison and cost control all break.

## 3. Who it is for

| Audience | The decision they are making |
|---|---|
| Lead-generation operators | Which market to build a lead-gen asset in |
| Marketing agencies | Whether a client's next market justifies budget |
| Local businesses | Whether a new service, suburb or city is worth entering |
| Entrepreneurs & researchers | Comparing opportunities systematically |

The MVP optimises for the first two. They run many markets, compare them, and
care about defensible reasoning.

## 4. The six signals

Every analysis is built from six signal families. These are fixed for the MVP —
adding a seventh is an architectural change, not a feature toggle.

| Signal | Question it answers |
|---|---|
| **Market demand** | How often and how urgently is this service sought? |
| **Competition** | How crowded is the market, and how deep is the auction? |
| **Advertising activity** | Who is advertising, how consistently, and is it growing? |
| **Business density** | How many businesses already serve this market, and how well? |
| **Customer value** | What is a typical job worth? |
| **Market trends** | Is interest growing, seasonal, or declining? |

Each is normalised to a comparable 0–100 sub-score with an attached confidence
level and its supporting evidence. The composite opportunity score is a
weighted combination — defined precisely in `04-signals-and-scoring.md`.

## 5. MVP scope

### In scope

1. Authenticated user enters a service + location.
2. Backend queues and executes a **research run** across the six signals.
3. Collected evidence is stored raw and structured, and is attributable.
4. AI layer weighs the evidence and writes the assessment.
5. Score, verdict and report are persisted and rendered in the web app.
6. User can view past runs and compare markets in a list.
7. A run is repeatable: re-running a market produces a new dated report.

### Out of scope for MVP

- Team accounts, seats, role permissions (single-user accounts only).
- Billing and subscriptions (early access is manually granted).
- PDF/white-label export.
- Scheduled automatic re-runs and change alerts.
- Bulk/CSV market upload.
- Public API for third parties.
- Non-English markets.
- Any signal outside the six above.

### Explicit non-goals

- Dvantora is **not** a keyword tool, rank tracker, or ad-spy tool. Those are
  inputs, not the product.
- Dvantora does **not** claim data partnerships. Source categories are
  described generically in public materials.
- Dvantora does **not** produce a score without the evidence behind it.

## 6. Product principles

These come from the approved public positioning and constrain the build.

1. **Evidence first.** Every verdict ships with the signals behind it. A claim
   in a report that cannot be traced to a stored piece of evidence is a bug.
2. **Explainable, not oracular.** A score without a "why" is another guess. The
   AI layer explains its reasoning in plain language.
3. **Local, specifically.** The unit of analysis is one service in one place.
4. **No single signal decides the verdict.** Search and advertising data is one
   input among many.

## 7. Content honesty rules (binding)

The marketing site is built on explicit honesty commitments. They apply to the
product too, and to anything the AI layer generates:

- The product is described as **in development** until it is not. No
  live-product claims, no invented customers, testimonials, partner logos or
  statistics.
- Any interface or figure that is not a real result is labelled as a preview
  with example data.
- Data-source categories are neutral descriptions, never partnership or
  endorsement claims.
- The demo market (*Plumbing — Brisbane, QLD*, score 87/100, businesses A–D) is
  fictional and must stay recognisably fictional.
- Generated report text must not invent a number. If a signal could not be
  collected, the report says so and the confidence drops.

## 8. Glossary

| Term | Meaning |
|---|---|
| **Market** | One service × one location. The canonical unit of analysis. |
| **Research run** (*run*) | One execution of the pipeline against one market, at a point in time. |
| **Collector** | A component that fetches raw data from one source. |
| **Evidence** | A stored, attributable raw observation from a collector. |
| **Signal** | One of the six families, normalised to 0–100 with confidence. |
| **Opportunity score** | The 0–100 composite of the six signals. |
| **Verdict** | Pursue / Watch / Pass, derived from the score and confidence. |
| **Report** | The rendered, decision-ready output of a completed run. |
| **Confidence** | How much evidence supports a signal or the overall score. |

## 9. Document index

| Doc | Status |
|---|---|
| `00-overview.md` | This document — draft |
| `01-architecture.md` | Approved for decisions 1, 2, 3, 5, 6, 7 · open on decision 4 |
| `02-data-model.md` | Not written |
| `03-research-pipeline.md` | Not written |
| `04-signals-and-scoring.md` | Not written |
| `05-api-contract.md` | Not written |
| `06-ai-analysis.md` | Not written |
| `07-data-sources.md` | **Written — INTERNAL, do not publish** |
| `08-frontend-integration.md` | Not written |
| `09-security-privacy.md` | Not written |
| `adr/0001`–`adr/0006` | Accepted |

`docs/` lives in the private `dvantora-engine` repository, per ADR-0001. It
must never be committed to the website repository, which deploys from its root
with crawling allowed; that repo's `.gitignore` excludes `docs/` as a guard.

## 10. Open questions

**Resolved**

1. ~~Freshness expectation~~ — **7 days**, configurable globally and per source,
   with a user-forcible re-run (ADR-0005).
2. ~~Cost per run~~ — **≈ $0.32** in live mode, **≈ $0.12** on standard queue,
   with a hard per-run ceiling of $0.75 (`07-data-sources.md` §8).

**Still open**

3. **Wall-clock target per run.** The site's illustrative timeline implies ~11
   minutes end to end. If that is the target, standard-queue vendor calls are
   affordable and cut data cost by roughly two thirds. Decide in
   `03-research-pipeline.md`.
4. **Supported countries.** The demo market is Australian. Several sources are
   geography-limited — notably Meta's Ad Library API, which returns commercial
   ads only for EU/UK and is therefore excluded (`07-data-sources.md` §4.3).
5. **Early access model** — invite-only with manually created accounts, or
   self-serve signup behind a waitlist gate?
6. **`app/` frontend stack** — decision 4 in `01-architecture.md`, still open,
   and the most expensive of the seven to reverse.
