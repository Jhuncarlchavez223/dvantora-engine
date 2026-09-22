"""Start (or reuse) a research run — shared by the JSON API and the app.

This is the single place that decides what "start a run" means: resolve the
market, reuse a run inside the freshness window (ADR-0005), enforce the monthly
quota, and queue a new run. Both `/api/v1/runs` and the server-rendered app call
it, so the two surfaces can never drift apart (docs/08-frontend-integration.md
§1.1).

Errors are raised as ApiError (e.g. market_ambiguous, quota_exceeded). Each
surface decides how to present them: the API returns JSON, the app re-renders
its form.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.collectors import live_sources
from engine.db import Conn, require
from engine.enums import RunTrigger
from engine.errors import invalid_request, quota_exceeded
from engine.markets import resolver
from engine.pipeline import queue


@dataclass(frozen=True)
class StartedRun:
    """What happened when a run was requested."""

    run_id: str
    status: str
    reused: bool  # True when an existing fresh run was returned instead
    resolution: resolver.Resolution
    data_age_hours: float | None = None  # only set when reused


def _quota_used(conn: Conn, account_id: str) -> int:
    return int(
        require(
            conn.execute(
                "SELECT count(*) AS c FROM research_runs "
                "WHERE requested_by=%s AND requested_at >= date_trunc('month', now())",
                (account_id,),
            ).fetchone()
        )["c"]
    )


def start_run(
    conn: Conn,
    account: dict[str, Any],
    *,
    service: str | None = None,
    location: str | None = None,
    market_key: str | None = None,
    force_refresh: bool = False,
    idempotency_key: str | None = None,
) -> StartedRun:
    """Resolve the market, then reuse a fresh run or queue a new one.

    Commits on success. Raises ApiError when the input cannot be resolved
    confidently, or when the account's monthly quota is spent.
    """
    if not market_key and not (service and location):
        raise invalid_request("Provide either market_key, or both service and location.")

    res = (
        resolver.resolve_by_key(conn, market_key)
        if market_key
        else resolver.resolve(conn, service or "", location or "")
    )

    if not force_refresh:
        # Only reuse a run built from the same live sources we'd use now.
        fresh = queue.find_fresh_run(conn, res.market_id, live_sources())
        if fresh:
            conn.commit()
            return StartedRun(
                run_id=str(fresh["id"]),
                status=fresh["status"],
                reused=True,
                resolution=res,
                data_age_hours=round(float(fresh["age_hours"]), 2),
            )

    if _quota_used(conn, account["id"]) >= account["run_quota_month"]:
        raise quota_exceeded()

    trigger = RunTrigger.FORCED_REFRESH if force_refresh else RunTrigger.USER
    run = queue.enqueue(conn, res.market_id, str(account["id"]), trigger, idempotency_key)
    conn.commit()
    return StartedRun(
        run_id=str(run["id"]),
        status=run["status"],
        reused=False,
        resolution=res,
    )
