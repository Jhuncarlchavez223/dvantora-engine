# dvantora-engine

Research engine for Dvantora. The specification in [`docs/`](docs/) is
authoritative — code follows the docs.

## Status: walking skeleton

One market goes from typed text to a stored, scored, explained report using
**local fixture data only**. Deliberately absent, pending approval:

| Not implemented | Gated by |
|---|---|
| Real data collectors | `07-data-sources.md` §12 verification |
| LLM analysis | ADR-0004 — only the `template` provider exists |
| Supabase (Postgres + Auth) | ADR-0002 — local Postgres for now; auth is a dev stub |
| Railway deployment | ADR-0003 |
| n8n | ADR-0006 — optional by design, absent by default |
| `app/` product UI | Decision 4 in `01-architecture.md` is still open |

The engine makes **no outbound network calls of any kind**.

## Run it locally

```bash
docker compose up -d postgres
cp .env.example .env

pip install -e ".[dev]"
psql "$DVANTORA_DATABASE_URL" -f db/migrations/0001_initial.sql
psql "$DVANTORA_DATABASE_URL" -f db/seed.sql

uvicorn engine.api.main:app --reload      # API   — terminal 1
python -m engine.pipeline.worker          # worker — terminal 2
```

```bash
curl -X POST localhost:8000/api/v1/runs \
  -H 'content-type: application/json' \
  -d '{"service":"Plumbing","location":"Brisbane, QLD"}'
# -> 202 {"run_id": "...", "status": "queued", ...}

curl localhost:8000/api/v1/runs/$RUN_ID          # poll until terminal
curl localhost:8000/api/v1/runs/$RUN_ID/report   # the report
```

## Checks

```bash
pytest        # 24 tests
ruff check .  # lint
mypy engine   # types
```

## Layout

```
db/migrations/   Hand-written forward-only SQL (02 §7)
db/seed.sql      Service and location taxonomy
engine/api/      FastAPI — implements 05-api-contract.md
engine/markets/  Canonical market resolution (00 §2, 02 §3.5)
engine/pipeline/ Postgres-backed queue, stage machine, run executor
engine/collectors/  Collector interface + fixture collector
engine/signals/  Normalisation and deterministic scoring (no model calls)
engine/ai/       Provider abstraction (ADR-0004) + template provider
tests/
```

## Three things worth knowing before changing anything

1. **The queue is Postgres.** `SELECT … FOR UPDATE SKIP LOCKED` in
   `engine/pipeline/queue.py`. There is no broker and none is needed.
2. **Scoring never calls a model.** Collection → normalisation → weighting →
   verdict is deterministic and unit-tested. The model only writes prose, and
   today no model is called at all.
3. **A failed collector must never fail a run.** It writes an `absent` evidence
   row; the run lands in `partial` and the report names the gap. Tests enforce
   this — see `tests/test_run_end_to_end.py`.

## Fixture data

Everything under `engine/collectors/fixtures/` is fictional data written for
development. It is not vendor output and not a real market measurement. Reports
generated from it say so in `analysis.caveats`.

## Provisional values

Scoring weights and normalisation curves carry `weights_version` /
`method_version` of `0.0-provisional`. They exist to prove the wiring.
`04-signals-and-scoring.md` supersedes them and has not been written.

## Notes

- Target runtime is Python 3.12 (`01-architecture.md` §4); the package accepts
  3.11+ and the suite was verified on 3.11.
- `engine/api/deps.py` resolves a fixed local account and refuses to run outside
  `DVANTORA_ENV=local`. It is not authentication.
