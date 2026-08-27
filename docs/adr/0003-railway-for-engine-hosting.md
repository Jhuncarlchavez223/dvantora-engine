# ADR-0003 — Railway for engine hosting

**Status:** Accepted
**Date:** 2026-08-27

## Context

A research run takes minutes, which rules out most serverless platforms.
The engine needs one always-on API process and one always-on worker process.

## Decision

Railway, Hobby plan, running two services from the same repository: a web
process and a worker process. Expected cost $5–15/mo at MVP volume.

## Consequences

- Long-running runs are unconstrained by platform execution limits.
- The worker can be scaled to more than one instance without code changes,
  because the queue uses `SKIP LOCKED`.
- Metered pricing means cost tracks usage rather than being flat — acceptable
  at this scale, worth re-checking if worker time grows.

## Reversal cost

Low. The engine deploys as a plain `Dockerfile` with configuration from
environment variables and no platform-specific SDKs, so moving to Render, Fly
or a VPS is a matter of pointing a new platform at the same repository. This
portability is a requirement, not an accident — do not adopt Railway-specific
runtime APIs.
