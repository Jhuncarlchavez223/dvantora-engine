"""Postgres-as-queue (01 §5, 02 §3.6). No Redis, no external broker."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Json

from engine.config import settings
from engine.db import Conn, require
from engine.enums import RunStatus, RunTrigger
from engine.errors import run_in_progress


def find_fresh_run(
    conn: Conn,
    market_id: str,
    required_sources: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """ADR-0005 — the freshness lookup this index exists for.

    `required_sources` maps each signal the engine currently collects live to
    the vendor that collects it, e.g. {"demand": "google_ads"}. A recent run is
    only returned if none of its evidence for those signals came from a
    different vendor. This stops an example-data (fixture) run from being reused
    when live data was expected. With no required sources, any recent run
    qualifies (the original behaviour).
    """
    required = required_sources or {}
    signals = list(required)
    vendors = [required[s] for s in signals]
    return conn.execute(
        """
        SELECT r.id, r.status, r.completed_at,
               EXTRACT(EPOCH FROM (now() - r.completed_at)) / 3600.0 AS age_hours
        FROM research_runs r
        WHERE r.market_id = %s
          AND r.status IN ('complete','partial')
          AND r.completed_at > now() - make_interval(hours => %s)
          AND NOT EXISTS (
              SELECT 1
              FROM evidence e
              JOIN unnest(%s::text[], %s::text[]) AS req(signal, vendor)
                ON e.signal::text = req.signal
              WHERE e.run_id = r.id
                AND e.vendor <> req.vendor
          )
        ORDER BY r.completed_at DESC
        LIMIT 1
        """,
        (market_id, settings.freshness_window_hours, signals, vendors),
    ).fetchone()


def enqueue(
    conn: Conn,
    market_id: str,
    account_id: str | None,
    trigger: RunTrigger = RunTrigger.USER,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if idempotency_key:
        existing = conn.execute(
            "SELECT * FROM research_runs WHERE requested_by = %s AND idempotency_key = %s",
            (account_id, idempotency_key),
        ).fetchone()
        if existing:
            return existing

    active = conn.execute(
        "SELECT id FROM research_runs WHERE market_id = %s AND status IN "
        "('queued','collecting','scoring','analyzing')",
        (market_id,),
    ).fetchone()
    if active:
        raise run_in_progress(str(active["id"]))

    return require(
        conn.execute(
            """
        INSERT INTO research_runs (market_id, requested_by, trigger, budget_cents,
                                   idempotency_key)
        VALUES (%s,%s,%s,%s,%s)
        RETURNING *
        """,
            (market_id, account_id, trigger.value, settings.run_budget_cents, idempotency_key),
        ).fetchone(),
        "inserted run",
    )


def claim_next(conn: Conn, worker_id: str) -> dict[str, Any] | None:
    """The claim query specified in 02 §3.6. SKIP LOCKED is what makes it safe."""
    return conn.execute(
        """
        UPDATE research_runs
           SET status = 'collecting',
               claimed_at = now(),
               claimed_by = %s,
               started_at = COALESCE(started_at, now()),
               attempt = attempt + 1
         WHERE id = (
             SELECT id FROM research_runs
              WHERE status = 'queued'
              ORDER BY requested_at
              FOR UPDATE SKIP LOCKED
              LIMIT 1
         )
        RETURNING *
        """,
        (worker_id,),
    ).fetchone()


def reap_stuck(conn: Conn) -> int:
    """02 §3.6 — without this, one worker crash strands a run forever."""
    rows = conn.execute(
        """
        UPDATE research_runs
           SET status = 'queued', claimed_at = NULL, claimed_by = NULL
         WHERE status IN ('collecting','scoring','analyzing')
           AND claimed_at < now() - make_interval(secs => %s)
        RETURNING id
        """,
        (settings.run_lease_seconds,),
    ).fetchall()
    return len(rows)


def set_status(
    conn: Conn,
    run_id: str,
    status: RunStatus,
    *,
    stage: str | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE research_runs
           SET status = %s,
               current_stage = COALESCE(%s, current_stage),
               error_code = %s,
               error_detail = %s,
               completed_at = CASE WHEN %s IN ('complete','partial','failed','cancelled')
                                   THEN now() ELSE completed_at END
         WHERE id = %s
        """,
        (status.value, stage, error_code, error_detail, status.value, run_id),
    )


def emit_event(conn: Conn, event_type: str, payload: dict[str, Any]) -> None:
    """ADR-0006: written in the same transaction as the state change.

    With no webhook URLs configured nothing delivers these, and nothing breaks.
    """
    conn.execute(
        "INSERT INTO events_outbox (event_type, payload) VALUES (%s, %s::jsonb)",
        (event_type, Json(payload)),
    )
