# ADR-0001 — Separate engine repository

**Status:** Accepted
**Date:** 2026-08-27

## Context

`dvantora-website` is a static marketing site with no build step and no
dependencies. The research engine is a Python service with a database, a worker
process and vendor credentials. A monorepo was considered and rejected.

The website repo deploys from its root with `robots.txt` allowing all crawlers,
so anything committed there is publicly readable. The specification contains
vendor pricing, cost-per-run economics and scoring design.

## Decision

Two repositories. `dvantora-website` stays exactly as it is. A new
`dvantora-engine` repository holds `docs/`, the engine, the app and any
automation exports.

## Consequences

- The website needs no restructure; the previously proposed `site/` move is cancelled.
- `docs/` must move out of the website repo before anything is pushed there.
- The app ships from the engine repo, so the API contract and its client are
  versioned together.
- Cross-repo coupling is limited to the public REST contract; the website never
  calls the API.
- Two deploy pipelines instead of one — accepted, since the website's pipeline
  is "copy files to a CDN" and never changes.

## Reversal cost

Moderate. Merging two repos later means rewriting deploy config and accepting
messy history. Kept cheap by having no shared code between them — only the
documented HTTP contract.
