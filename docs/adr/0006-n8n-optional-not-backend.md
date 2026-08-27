# ADR-0006 — n8n is an optional integration layer, not the backend

**Status:** Accepted
**Date:** 2026-08-27

## Context

n8n was originally anticipated as the backend for forms and possibly for
orchestration. Business logic inside a visual workflow is not reviewable in
diff, not unit-testable, and not readable by an AI coding assistant — the three
properties this project most depends on. A paid subscription is also not
warranted before there are users.

## Decision

The engine is the application backend. n8n is optional and may be added later,
or never. The research engine must run to completion with no n8n instance
reachable.

The engine permanently owns: run orchestration, the stage state machine, all
collectors, signal normalisation, scoring, verdict thresholds, LLM calls,
evidence TTL purging, and scheduled re-runs.

n8n may own, when adopted: form intake, notification email, event fan-out, ops
alerts, and triggering scheduled research through the public API.

## Consequences

- No n8n subscription is required to build or launch.
- The engine emits domain events to a configured list of signed webhook URLs.
  An empty list — the default — means nothing is emitted and nothing breaks.
- Event delivery is asynchronous and bounded-retry; it never blocks or fails a run.
- Because the target is a signed webhook URL, the receiver can be n8n, Zapier,
  Make, a Lambda or a script. n8n is one option, not the design.
- n8n never touches the database directly; it uses `/api/v1/*` with a service
  token, exactly as the app does.
- The marketing site keeps its `mailto:` contact card until an intake path exists.

## Reversal cost

Very low in the adopt direction — the seam already exists. The expensive
direction would be the opposite one: letting orchestration drift into n8n and
later needing to extract it. The hard rule in `01-architecture.md` §7.1 exists
to prevent that drift.
