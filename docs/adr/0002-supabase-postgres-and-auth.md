# ADR-0002 — Supabase for Postgres and authentication

**Status:** Accepted
**Date:** 2026-08-27

## Context

The engine needs a Postgres database (which also serves as the job queue) and
user authentication. Building auth — signup, login, password reset, session
handling, token issuance — is a significant time cost that adds no product
value for a solo founder.

## Decision

Supabase provides both. Free tier during development; Pro ($25/mo) from the
point real users can log in, because free-tier projects pause after a week of
inactivity and cap at 500 MB.

## Consequences

- Auth is configuration rather than a subsystem to build and maintain.
- The database is ordinary Postgres, so `SELECT … FOR UPDATE SKIP LOCKED` as
  the job queue works without extra infrastructure.
- Row-level security is available if multi-tenant isolation is needed later.
- Storage growth needs watching: raw evidence will grow faster than expected
  against an 8 GB Pro allowance. `02-data-model.md` must decide early whether
  large raw payloads live in the database or in object storage behind a pointer.

## Reversal cost

Moderate. Data migrates easily — it is plain Postgres. Auth is the sticky part:
user records, password hashes and session issuance. Kept cheap by routing every
JWT validation through a single module in the engine, so the auth provider is
one file's worth of change.
