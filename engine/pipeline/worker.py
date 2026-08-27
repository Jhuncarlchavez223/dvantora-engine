"""Run executor. Collect -> score -> analyse -> finalise (01 §5).

Fail-soft is the governing rule: a collector that fails records an `absent`
evidence row, the run continues, and the report declares the gap.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from psycopg.types.json import Json

from engine.ai.provider import AnalysisRequest, get_provider
from engine.collectors.base import MarketRef
from engine.collectors.fixture import build_collectors
from engine.config import settings
from engine.db import Conn, require
from engine.enums import (
    SIGNAL_STAGES,
    EvidenceStatus,
    RunStage,
    RunStatus,
    SignalKey,
    StageStatus,
)
from engine.pipeline import queue, stages
from engine.report import build as build_report
from engine.signals.normalise import Normalised, normalise, unavailable
from engine.signals.score import InsufficientEvidence, compute

log = logging.getLogger("dvantora.worker")


def _market_ref(row: dict[str, Any]) -> MarketRef:
    return MarketRef(
        market_id=str(row["market_id"]),
        market_key=row["market_key"],
        service_slug=row["service_slug"],
        location_slug=row["location_slug"],
        display_name=f"{row['service_name']} — {row['location_name']}",
        population=row["population"],
    )


def _load_run(conn: Conn, run_id: str) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT r.*, m.market_key, m.id AS market_id,
               s.slug AS service_slug, s.display_name AS service_name,
               l.slug AS location_slug, l.display_name AS location_name,
               l.granularity, l.population
        FROM research_runs r
        JOIN markets m ON m.id = r.market_id
        JOIN services s ON s.id = m.service_id
        JOIN locations l ON l.id = m.location_id
        WHERE r.id = %s
        """,
        (run_id,),
    ).fetchone()


def _store_evidence(conn: Conn, run_id: str, market_id: str, result: Any) -> None:
    conn.execute(
        """
        INSERT INTO evidence (run_id, market_id, signal, collector, vendor, endpoint,
                              status, payload, source_url, expires_at, cost_cents, request_hash)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,
                CASE WHEN %s::int IS NULL THEN NULL
                     ELSE now() + make_interval(days => %s::int) END,
                %s,%s)
        """,
        (
            run_id,
            market_id,
            result.signal.value,
            f"fixture.{result.signal.value}",
            result.vendor,
            result.endpoint,
            result.status.value,
            Json(result.payload),
            result.source_url,
            result.retention_days,
            result.retention_days,
            result.cost_cents,
            result.request_hash,
        ),
    )


def execute_run(conn: Conn, run_id: str) -> str:
    run = _load_run(conn, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")

    market = _market_ref(run)
    stages.initialise(conn, run_id)

    stages.start(conn, run_id, RunStage.RESOLVE)
    stages.finish(conn, run_id, RunStage.RESOLVE, StageStatus.OK)

    # ---------------------------------------------------------------- collect
    collected: dict[SignalKey, list[dict[str, Any]]] = {}
    failures: dict[SignalKey, str] = {}
    spend = 0.0

    for collector in build_collectors():
        stage = SIGNAL_STAGES[collector.signal]
        stages.start(conn, run_id, stage)
        try:
            results = collector.collect(market)
        except Exception as exc:  # a collector must never end the run
            log.warning("collector %s raised: %s", collector.name, exc)
            failures[collector.signal] = "collector_exception"
            stages.finish(conn, run_id, stage, StageStatus.FAILED, "collector_exception", str(exc))
            continue

        ok_payloads = []
        for result in results:
            _store_evidence(conn, run_id, market.market_id, result)
            spend += float(result.cost_cents)
            if result.status is EvidenceStatus.OK:
                ok_payloads.append(result.payload)
            else:
                failures[collector.signal] = result.payload.get("reason", result.status.value)

        if ok_payloads:
            collected[collector.signal] = ok_payloads
            stages.finish(conn, run_id, stage, StageStatus.OK)
        else:
            stages.finish(
                conn,
                run_id,
                stage,
                StageStatus.FAILED,
                failures.get(collector.signal, "unavailable"),
            )

    conn.execute("UPDATE research_runs SET spend_cents=%s WHERE id=%s", (int(spend), run_id))

    # ---------------------------------------------------------------- score
    queue.set_status(conn, run_id, RunStatus.SCORING, stage=RunStage.SCORE.value)
    stages.start(conn, run_id, RunStage.SCORE)

    normalised: list[Normalised] = []
    for signal in SignalKey:
        if signal in collected:
            normalised.append(
                normalise(
                    signal,
                    collected[signal],
                    market.population,
                    run["granularity"],
                )
            )
        else:
            normalised.append(unavailable(signal, failures.get(signal, "unavailable")))

    for n in normalised:
        conn.execute(
            """
            INSERT INTO signals (run_id, signal, score, confidence, band, inputs,
                                 method_version, notes)
            VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
            ON CONFLICT (run_id, signal) DO UPDATE
              SET score=EXCLUDED.score, confidence=EXCLUDED.confidence, band=EXCLUDED.band,
                  inputs=EXCLUDED.inputs, notes=EXCLUDED.notes
            """,
            (
                run_id,
                n.signal.value,
                n.score,
                n.confidence,
                n.band.value,
                Json(n.inputs),
                n.method_version,
                n.notes,
            ),
        )

    try:
        score = compute(normalised)
    except InsufficientEvidence as exc:
        # 00 §5: no score is invented from too little evidence.
        stages.finish(conn, run_id, RunStage.SCORE, StageStatus.FAILED, "insufficient_evidence")
        for stage in (RunStage.ANALYZE, RunStage.FINALIZE):
            stages.finish(conn, run_id, stage, StageStatus.SKIPPED)
        queue.set_status(
            conn,
            run_id,
            RunStatus.FAILED,
            stage=RunStage.SCORE.value,
            error_code="insufficient_evidence",
            error_detail=f"signal coverage {exc.coverage:.2f} below minimum",
        )
        queue.emit_event(conn, "run.failed", {"run_id": run_id, "reason": "insufficient_evidence"})
        conn.commit()
        return RunStatus.FAILED.value

    conn.execute(
        """
        INSERT INTO scores (run_id, opportunity_score, verdict, confidence, weights_version)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (run_id) DO UPDATE
          SET opportunity_score=EXCLUDED.opportunity_score, verdict=EXCLUDED.verdict,
              confidence=EXCLUDED.confidence, weights_version=EXCLUDED.weights_version,
              computed_at=now()
        """,
        (
            run_id,
            score.opportunity_score,
            score.verdict.value,
            score.confidence,
            score.weights_version,
        ),
    )
    stages.finish(conn, run_id, RunStage.SCORE, StageStatus.OK)

    # ---------------------------------------------------------------- analyse
    queue.set_status(conn, run_id, RunStatus.ANALYZING, stage=RunStage.ANALYZE.value)
    stages.start(conn, run_id, RunStage.ANALYZE)

    missing = [n.signal.value for n in normalised if n.score is None]
    provider = get_provider(settings.ai_provider)
    analysis = provider.analyse(
        AnalysisRequest(
            market_display_name=market.display_name,
            opportunity_score=score.opportunity_score,
            verdict=score.verdict.value,
            confidence=score.confidence,
            signals=[
                {
                    "signal": n.signal.value,
                    "score": float(n.score) if n.score is not None else None,
                    "band": n.band.value,
                    "confidence": n.confidence,
                    "headline": n.headline,
                }
                for n in normalised
            ],
            missing_signals=missing,
            gates_applied=list(score.gates_applied),
        )
    )
    stages.finish(conn, run_id, RunStage.ANALYZE, StageStatus.OK)

    # ---------------------------------------------------------------- finalise
    stages.start(conn, run_id, RunStage.FINALIZE)

    sample_expiry = require(
        conn.execute(
            "SELECT max(expires_at) AS e FROM evidence WHERE run_id=%s AND expires_at IS NOT NULL",
            (run_id,),
        ).fetchone()
    )["e"]

    sources = conn.execute(
        "SELECT DISTINCT signal::text AS signal, vendor, max(fetched_at) AS fetched_at "
        "FROM evidence WHERE run_id=%s AND status='ok' GROUP BY signal, vendor",
        (run_id,),
    ).fetchall()

    trend_payloads = collected.get(SignalKey.TRENDS, [])
    payload = build_report(
        run=run,
        market={
            "market_key": market.market_key,
            "service": {"slug": run["service_slug"], "display_name": run["service_name"]},
            "location": {
                "slug": run["location_slug"],
                "display_name": run["location_name"],
                "granularity": run["granularity"],
            },
        },
        normalised=normalised,
        score=score,
        analysis=analysis,
        density_payloads=collected.get(SignalKey.DENSITY, []),
        trend_payload=trend_payloads[0] if trend_payloads else None,
        sample_expires_at=sample_expiry.isoformat() if sample_expiry else None,
        sources=[
            {
                "signal": s["signal"],
                "vendor": s["vendor"],
                "fetched_at": s["fetched_at"].isoformat(),
            }
            for s in sources
        ],
        data_age_hours=0.0,
    )

    conn.execute(
        """
        INSERT INTO reports (run_id, payload, generator, provider, model, prompt_version)
        VALUES (%s,%s::jsonb,%s,%s,%s,%s)
        ON CONFLICT (run_id) DO UPDATE
          SET payload=EXCLUDED.payload, generator=EXCLUDED.generator,
              generated_at=now()
        """,
        (
            run_id,
            Json(payload),
            analysis.generator.value,
            analysis.provider,
            analysis.model,
            analysis.prompt_version,
        ),
    )

    final = RunStatus.PARTIAL if missing else RunStatus.COMPLETE
    stages.finish(conn, run_id, RunStage.FINALIZE, StageStatus.OK)
    queue.set_status(conn, run_id, final, stage=RunStage.FINALIZE.value)
    queue.emit_event(
        conn,
        "run.completed",
        {"run_id": run_id, "status": final.value, "market_key": market.market_key},
    )
    conn.commit()
    return final.value


def run_forever(poll_seconds: float = 2.0) -> None:  # pragma: no cover - dev loop
    from engine.db import connection

    worker_id = f"worker-{os.getpid()}"
    log.info("worker %s started (collector_mode=%s)", worker_id, settings.collector_mode)
    while True:
        with connection() as conn:
            queue.reap_stuck(conn)
            claimed = queue.claim_next(conn, worker_id)
            conn.commit()
        if claimed is None:
            time.sleep(poll_seconds)
            continue
        with connection() as conn:
            try:
                execute_run(conn, str(claimed["id"]))
            except Exception as exc:
                conn.rollback()
                log.exception("run %s crashed", claimed["id"])
                queue.set_status(
                    conn,
                    str(claimed["id"]),
                    RunStatus.FAILED,
                    error_code="worker_error",
                    error_detail=str(exc),
                )
                conn.commit()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    run_forever()
