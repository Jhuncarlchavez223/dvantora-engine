"""Run endpoints (05-api-contract.md §3, §4, §6, §7, §8)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, Query, Response
from pydantic import BaseModel, Field

from engine.api.deps import current_account
from engine.config import settings
from engine.db import Conn, connection, require
from engine.enums import ALL_STAGES, TERMINAL_STATUSES, RunStatus
from engine.errors import forbidden, invalid_request, not_found, report_not_ready
from engine.markets import resolver
from engine.pipeline import queue
from engine.pipeline.start import start_run

router = APIRouter()

POLL_AFTER_MS = 3000


class CreateRunRequest(BaseModel):
    service: str | None = None
    location: str | None = None
    market_key: str | None = None
    force_refresh: bool = Field(default=False)


def _market_block(res: resolver.Resolution) -> dict[str, Any]:
    return {
        "market_key": res.market_key,
        "service": res.service,
        "location": res.location,
        "resolution": {"method": res.method.value, "confidence": res.confidence},
    }


@router.post("/runs")
def create_run(
    body: CreateRunRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    with connection() as conn:
        account = current_account(conn)
        started = start_run(
            conn,
            account,
            service=body.service,
            location=body.location,
            market_key=body.market_key,
            force_refresh=body.force_refresh,
            idempotency_key=idempotency_key,
        )

    if started.reused:
        response.status_code = 200
        return {
            "run_id": started.run_id,
            "status": started.status,
            "reused": True,
            "data_age_hours": started.data_age_hours,
            "freshness_window_hours": settings.freshness_window_hours,
            "market": _market_block(started.resolution),
            "report_url": f"/api/v1/runs/{started.run_id}/report",
        }

    response.status_code = 202
    return {
        "run_id": started.run_id,
        "status": started.status,
        "reused": False,
        "market": _market_block(started.resolution),
        "poll_after_ms": POLL_AFTER_MS,
    }


def _load_run_or_404(conn: Conn, run_id: str, account_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT r.*, m.market_key,
               s.slug AS service_slug, s.display_name AS service_name,
               l.slug AS location_slug, l.display_name AS location_name, l.granularity
        FROM research_runs r
        JOIN markets m ON m.id = r.market_id
        JOIN services s ON s.id = m.service_id
        JOIN locations l ON l.id = m.location_id
        WHERE r.id = %s
        """,
        (run_id,),
    ).fetchone()
    if not row:
        raise not_found("No such run.")
    if row["requested_by"] is not None and str(row["requested_by"]) != str(account_id):
        raise forbidden()
    return row


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    with connection() as conn:
        account = current_account(conn)
        run = _load_run_or_404(conn, run_id, account["id"])
        stage_rows = conn.execute(
            "SELECT stage::text AS stage, status::text AS status, started_at, finished_at, "
            "error_code FROM run_stages WHERE run_id=%s",
            (run_id,),
        ).fetchall()
        conn.commit()

    by_stage = {r["stage"]: r for r in stage_rows}
    stages = []
    for stage in ALL_STAGES:
        row = by_stage.get(stage.value)
        entry: dict[str, Any] = {
            "stage": stage.value,
            "status": row["status"] if row else "pending",
        }
        if row:
            if row["started_at"]:
                entry["started_at"] = row["started_at"].isoformat()
            if row["finished_at"]:
                entry["finished_at"] = row["finished_at"].isoformat()
            if row["error_code"]:
                entry["error_code"] = row["error_code"]
        stages.append(entry)

    done = sum(1 for s in stages if s["status"] in ("ok", "failed", "skipped"))
    terminal = run["status"] in {s.value for s in TERMINAL_STATUSES}

    return {
        "run_id": str(run["id"]),
        "status": run["status"],
        "current_stage": run["current_stage"],
        "market": {
            "market_key": run["market_key"],
            "service": {"slug": run["service_slug"], "display_name": run["service_name"]},
            "location": {
                "slug": run["location_slug"],
                "display_name": run["location_name"],
                "granularity": run["granularity"],
            },
        },
        "requested_at": run["requested_at"].isoformat(),
        "started_at": run["started_at"].isoformat() if run["started_at"] else None,
        "completed_at": run["completed_at"].isoformat() if run["completed_at"] else None,
        "progress": {"completed": done, "total": len(stages)},
        "stages": stages,
        "error_code": run["error_code"],
        "poll_after_ms": None if terminal else POLL_AFTER_MS,
    }


@router.get("/runs/{run_id}/report")
def get_report(run_id: str) -> dict[str, Any]:
    with connection() as conn:
        account = current_account(conn)
        run = _load_run_or_404(conn, run_id, account["id"])
        row = conn.execute(
            "SELECT payload, generated_at FROM reports WHERE run_id=%s", (run_id,)
        ).fetchone()
        conn.commit()
    if not row:
        raise report_not_ready(run["status"])

    payload = dict(row["payload"])
    payload["generated_at"] = row["generated_at"].isoformat()
    if run["completed_at"]:
        age = (datetime.now(UTC) - run["completed_at"]).total_seconds()
        payload["data_age_hours"] = round(age / 3600.0, 2)
    return payload


@router.get("/runs/{run_id}/evidence")
def get_evidence(
    run_id: str,
    signal: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
) -> dict[str, Any]:
    with connection() as conn:
        account = current_account(conn)
        _load_run_or_404(conn, run_id, account["id"])
        sql = (
            "SELECT signal::text AS signal, vendor, endpoint, status::text AS status, "
            "fetched_at, expires_at, source_url, payload FROM evidence WHERE run_id=%s"
        )
        params: list[Any] = [run_id]
        if signal:
            sql += " AND signal=%s"
            params.append(signal)
        sql += " ORDER BY fetched_at LIMIT %s"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        purged = require(
            conn.execute(
                "SELECT count(*) AS c FROM evidence WHERE run_id=%s AND expires_at < now()",
                (run_id,),
            ).fetchone()
        )["c"]
        conn.commit()

    return {
        "items": [
            {
                "signal": r["signal"],
                "vendor": r["vendor"],
                "endpoint": r["endpoint"],
                "status": r["status"],
                "fetched_at": r["fetched_at"].isoformat(),
                "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
                "source_url": r["source_url"],
                "payload": r["payload"],
            }
            for r in rows
        ],
        "purged_count": purged,
    }


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, Any]:
    with connection() as conn:
        account = current_account(conn)
        run = _load_run_or_404(conn, run_id, account["id"])
        if run["status"] in {s.value for s in TERMINAL_STATUSES}:
            raise invalid_request("Run is already finished.")
        queue.set_status(conn, run_id, RunStatus.CANCELLED)
        conn.commit()
    return {"run_id": run_id, "status": RunStatus.CANCELLED.value}


@router.get("/runs")
def list_runs(limit: int = Query(default=20, le=100)) -> dict[str, Any]:
    with connection() as conn:
        account = current_account(conn)
        rows = conn.execute(
            """
            SELECT r.id, r.status::text AS status, r.requested_at, r.completed_at,
                   m.market_key, s.display_name AS service_name,
                   l.display_name AS location_name,
                   sc.opportunity_score, sc.verdict::text AS verdict
            FROM research_runs r
            JOIN markets m ON m.id = r.market_id
            JOIN services s ON s.id = m.service_id
            JOIN locations l ON l.id = m.location_id
            LEFT JOIN scores sc ON sc.run_id = r.id
            WHERE r.requested_by = %s
            ORDER BY r.requested_at DESC
            LIMIT %s
            """,
            (account["id"], limit),
        ).fetchall()
        conn.commit()

    return {
        "items": [
            {
                "run_id": str(r["id"]),
                "status": r["status"],
                "market": {
                    "market_key": r["market_key"],
                    "display_name": f"{r['service_name']} — {r['location_name']}",
                },
                "opportunity_score": float(r["opportunity_score"])
                if r["opportunity_score"] is not None
                else None,
                "verdict": r["verdict"],
                "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            }
            for r in rows
        ],
        "next_cursor": None,
        "has_more": False,
    }


@router.get("/markets/{market_key}/runs")
def market_history(market_key: str, limit: int = Query(default=20, le=100)) -> dict[str, Any]:
    with connection() as conn:
        current_account(conn)
        rows = conn.execute(
            """
            SELECT r.id, r.status::text AS status, r.completed_at,
                   sc.opportunity_score, sc.verdict::text AS verdict
            FROM research_runs r
            JOIN markets m ON m.id = r.market_id
            LEFT JOIN scores sc ON sc.run_id = r.id
            WHERE m.market_key = %s
            ORDER BY r.requested_at DESC
            LIMIT %s
            """,
            (market_key, limit),
        ).fetchall()
        conn.commit()
    return {
        "items": [
            {
                "run_id": str(r["id"]),
                "status": r["status"],
                "opportunity_score": float(r["opportunity_score"])
                if r["opportunity_score"] is not None
                else None,
                "verdict": r["verdict"],
                "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            }
            for r in rows
        ],
        "next_cursor": None,
        "has_more": False,
    }
