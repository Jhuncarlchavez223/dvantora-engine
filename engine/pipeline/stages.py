"""Stage bookkeeping for the run timeline the app renders (05 §4)."""

from __future__ import annotations

from engine.db import Conn
from engine.enums import ALL_STAGES, RunStage, StageStatus


def initialise(conn: Conn, run_id: str) -> None:
    for stage in ALL_STAGES:
        conn.execute(
            "INSERT INTO run_stages (run_id, stage, status) VALUES (%s,%s,'pending') "
            "ON CONFLICT (run_id, stage, attempt) DO NOTHING",
            (run_id, stage.value),
        )


def start(conn: Conn, run_id: str, stage: RunStage) -> None:
    conn.execute(
        "UPDATE run_stages SET status='running', started_at=now() WHERE run_id=%s AND stage=%s",
        (run_id, stage.value),
    )
    conn.execute("UPDATE research_runs SET current_stage=%s WHERE id=%s", (stage.value, run_id))


def finish(
    conn: Conn,
    run_id: str,
    stage: RunStage,
    status: StageStatus,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> None:
    conn.execute(
        "UPDATE run_stages SET status=%s, finished_at=now(), error_code=%s, error_detail=%s "
        "WHERE run_id=%s AND stage=%s",
        (status.value, error_code, error_detail, run_id, stage.value),
    )
