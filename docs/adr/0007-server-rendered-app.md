# ADR-0007 — Server-rendered app: FastAPI + Jinja2 + HTMX

**Status:** Accepted
**Date:** 2026-08-27
**Closes:** Decision 4 in `01-architecture.md` §10

## Context

`app/` is the authenticated product surface: new analysis, run progress, report,
market list. Four screens. Decision 4 was left open through the walking skeleton
because it is the most expensive of the seven decisions to reverse.

Three facts shaped the choice, and only became clear once the engine existed:

1. The engine is already a FastAPI service. A second runtime would be the first
   piece of infrastructure not justified by the work.
2. The one genuinely dynamic screen is run progress, whose interaction model is
   **polling a stage list** — decided in `01 §8` for reasons unrelated to the
   frontend.
3. The marketing site already carries a finished design system: 48KB of CSS with
   design tokens at the top, and hand-written HTML for the three product views.
   Templates can adopt that markup nearly verbatim.

## Decision

The app is **server-rendered by the same FastAPI application that serves the API**:
Jinja2 templates, HTMX for partial updates, no build step, no second deploy
target, same origin.

`engine/app/` holds routes, templates and static assets. `/app/*` returns HTML;
`/api/v1/*` continues to return JSON and remains the contract for automation and
any future client.

## Alternatives considered

**Static SPA (vanilla JS, reusing `main.css`).** Zero build and independently
deployable, and it was the earlier recommendation. Rejected because an
authenticated app needs routing, session state, polling and DOM reconciliation
hand-written with no framework conventions — the part where AI assistance helps
least, and the part a solo founder maintains forever.

**Next.js / React.** Best long-term fit for a rich client and the most AI-assist
training data. Rejected for the MVP: a second runtime, a second deploy target and
server-side rendering that is pointless behind a login, in exchange for capability
four screens do not need.

**Separate FastAPI app for the UI.** Same technology, own process. Rejected as
strictly worse than one process: it reintroduces cross-origin handling and a second
deploy for no isolation the product needs.

## Consequences

- No CORS, no preflight, no browser-side token storage. `05 §11` question 1
  resolves to same-origin.
- Auth is a Supabase **session cookie** validated server-side, not a JWT held in
  JavaScript. One dependency resolves the account for both surfaces.
- Polling is one HTMX attribute against a rendered fragment instead of hand-written
  fetch-and-rerender.
- **The UI ships with the engine.** A copy change redeploys the API process. This
  is the real cost of the decision and it is accepted at MVP scale.
- App routes must call the same internal functions the API routes call. If business
  logic starts appearing in templates or view handlers, this ADR has been violated
  and the reversal cost below stops being true.
- `05-api-contract.md` is no longer the only consumer-facing surface, but remains
  the only contract with external stability guarantees. Nothing under `/app/*` is
  a public interface.

## Reversal cost

**Moderate — the highest of the seven, and bounded by construction.** Moving to a
client-side framework later means rewriting the view layer only, because the JSON
API already exists and the templates hold no business logic. Days, not a rewrite of
the product.

The thing that would make it expensive is logic leaking into the view layer. The
rule in Consequences is what keeps this estimate honest.
