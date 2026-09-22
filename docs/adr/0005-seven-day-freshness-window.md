# ADR-0005 — Seven-day freshness window

**Status:** Accepted
**Date:** 2026-08-27
**Amended:** 2026-09-23 (see Amendment below)

## Context

Research costs money per run (~$0.32 live, ~$0.12 standard queue — see
`07-data-sources.md` §8). Popular markets overlap heavily between users. Some
underlying data changes slowly: Google's keyword historical metrics refresh
monthly, and business profiles change over weeks.

## Decision

A completed run less than 7 days old satisfies a new request for the same
canonical market. Users can force a fresh run. The window is configurable
globally and per source, and is never a literal in pipeline code.

## Consequences

- Cost scales with distinct markets researched, not with users or page views.
- Requires canonical market resolution to work correctly — if "Plumbing,
  Brisbane" and "plumber brisbane qld" resolve to different markets, the cache
  never hits. This makes market normalisation a correctness requirement, not a
  nicety.
- Per-source windows let fast-moving signals (advertising activity) refresh more
  often than slow ones (business listings) within the same run.
- Reports must display the age of the data they are based on.

## Reversal cost

Trivial, because it is configuration from day one. The dependency that is *not*
trivial is canonical market resolution, which is why it is specified in
`00-overview.md` §2 rather than left to implementation.

## Amendment — 2026-09-23: reuse only runs built from matching sources

**Context.** Once the first live collector existed (Google Ads for Demand), a
recent run built entirely from example (fixture) data could satisfy a request
that expected live data. Reports stayed honestly labelled, but a user asking
for live research could silently receive example data for up to 7 days.

**Decision.** A recent run satisfies a new request only if, for every signal the
engine currently collects from a live source, that run's evidence for the signal
came from the same vendor. With no live sources configured (fixture mode), any
recent run qualifies, as before.

This is decided from the **stored evidence** — what actually happened — not from
a mode recorded when the run was requested. The API and the worker can run in
different collector modes, so a request-time label could be wrong.

Implemented by `engine.collectors.live_sources()` and the `required_sources`
check in `engine.pipeline.queue.find_fresh_run`.

**Consequences.**

- An example-data run is never returned in place of live data.
- A genuinely live run is still reused, so quota and cost savings are kept.
- Changing a signal's source later (for example, adding Places for Business
  Density) automatically stops older runs from being reused for that signal.
- No database schema change was needed.
