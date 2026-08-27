# ADR-0004 — LLM access behind a provider abstraction

**Status:** Accepted
**Date:** 2026-08-27

## Context

One model writes the report prose from structured evidence. It does not compute
the score. Model pricing, availability and quality move quickly, and the
product should not be coupled to one vendor's SDK.

## Decision

All model access goes through a single internal interface exposing structured
output against a JSON Schema. Provider and model are configuration values. No
provider SDK is imported anywhere outside `ai/providers/`, enforced by a lint
rule.

## Consequences

- Switching providers is a configuration change plus one adapter file.
- The interface is defined in terms of schema-validated structured output,
  because that is the capability actually depended on.
- Every report stores the provider, model and prompt version used, so any past
  report can be explained or reproduced.
- Prompts are tuned per model, so a switch still requires re-running the eval
  set — the abstraction removes the plumbing cost, not the quality cost.
- Estimated cost ~$0.03–0.08 per run at mid-tier pricing.

## Reversal cost

Low by construction. The risk is erosion: a provider-specific feature leaking
into calling code. The lint rule and the eval set are what keep this ADR true
over time.
