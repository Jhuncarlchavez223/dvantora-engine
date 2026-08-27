"""Assembles the report payload specified in 05-api-contract.md §6."""

from __future__ import annotations

from typing import Any

from engine.ai.provider import AnalysisResult
from engine.enums import SignalKey
from engine.signals.normalise import Normalised
from engine.signals.score import Score

REPORT_SCHEMA_VERSION = "1"


def _signal_block(n: Normalised) -> dict[str, Any]:
    return {
        "signal": n.signal.value,
        "score": float(n.score) if n.score is not None else None,
        "band": n.band.value,
        "confidence": round(n.confidence, 3),
        "headline": n.headline,
        "inputs": n.inputs,
        "notes": n.notes,
    }


def build(
    *,
    run: dict[str, Any],
    market: dict[str, Any],
    normalised: list[Normalised],
    score: Score,
    analysis: AnalysisResult,
    density_payloads: list[dict[str, Any]],
    trend_payload: dict[str, Any] | None,
    sample_expires_at: str | None,
    sources: list[dict[str, Any]],
    data_age_hours: float,
) -> dict[str, Any]:
    aggregates = next((p for p in density_payloads if p.get("kind") == "aggregates"), {})
    sample = next((p for p in density_payloads if p.get("kind") == "sample"), None)

    trend = None
    if trend_payload:
        trend_signal = next((n for n in normalised if n.signal is SignalKey.TRENDS), None)
        trend = {
            "granularity": trend_payload.get("granularity", "unknown"),
            "note": trend_signal.notes if trend_signal else None,
            "series": trend_payload.get("series", []),
        }

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": str(run["id"]),
        "market": market,
        "generated_at": None,  # set by the API from reports.generated_at
        "data_age_hours": round(data_age_hours, 2),
        "score": {
            "opportunity_score": score.opportunity_score,
            "verdict": score.verdict.value,
            "confidence": score.confidence,
        },
        "signals": [_signal_block(n) for n in normalised],
        "trend": trend,
        "businesses": {
            # 05 §6.1 rule 2: `sample` legitimately disappears after its TTL while
            # `aggregates` remain. Clients must render this state normally.
            "available": sample is not None,
            "expires_at": sample_expires_at,
            "aggregates": aggregates,
            "sample": sample.get("businesses") if sample else None,
        },
        "analysis": {
            "generator": analysis.generator.value,
            "summary": analysis.summary,
            "reasons": analysis.reasons,
            "recommended_action": analysis.recommended_action,
            "caveats": analysis.caveats,
        },
        "provenance": {
            "weights_version": score.weights_version,
            "coverage": score.coverage,
            "gates_applied": list(score.gates_applied),
            "prompt_version": analysis.prompt_version,
            "provider": analysis.provider,
            "model": analysis.model,
            "sources": sources,
        },
    }
