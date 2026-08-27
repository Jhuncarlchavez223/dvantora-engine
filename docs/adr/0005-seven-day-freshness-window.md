# ADR-0005 — Seven-day freshness window

**Status:** Accepted
**Date:** 2026-08-27

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
