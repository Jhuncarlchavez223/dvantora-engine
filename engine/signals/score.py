"""Deterministic composite scoring. No network, no model calls (01 §6).

PROVISIONAL weights — `04-signals-and-scoring.md` supersedes this file.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.config import settings
from engine.enums import SignalKey, Verdict
from engine.signals.normalise import Normalised

WEIGHTS: dict[SignalKey, float] = {
    SignalKey.DEMAND: 0.25,
    SignalKey.COMPETITION: 0.20,
    SignalKey.ADVERTISING: 0.15,
    SignalKey.DENSITY: 0.15,
    SignalKey.CUSTOMER_VALUE: 0.15,
    SignalKey.TRENDS: 0.10,
}

PURSUE_AT = 70.0
WATCH_AT = 45.0


@dataclass(frozen=True)
class Score:
    opportunity_score: float
    verdict: Verdict
    confidence: float
    coverage: float
    weights_version: str = settings.weights_version


class InsufficientEvidence(Exception):
    """Raised when too little evidence exists to score honestly (00 §5)."""

    def __init__(self, coverage: float) -> None:
        super().__init__(f"coverage {coverage:.2f} below minimum")
        self.coverage = coverage


def compute(normalised: list[Normalised]) -> Score:
    available = [n for n in normalised if n.score is not None]
    total_weight = sum(WEIGHTS.values())
    covered_weight = sum(WEIGHTS[n.signal] for n in available)
    coverage = covered_weight / total_weight if total_weight else 0.0

    if coverage < settings.min_coverage_to_score:
        raise InsufficientEvidence(coverage)

    # Weights are renormalised over available signals: a missing signal must not
    # silently drag the score toward zero.
    score = sum((n.score or 0.0) * WEIGHTS[n.signal] for n in available) / covered_weight
    weighted_conf = sum(n.confidence * WEIGHTS[n.signal] for n in available) / covered_weight
    confidence = weighted_conf * coverage

    verdict = (
        Verdict.PURSUE
        if score >= PURSUE_AT
        else Verdict.WATCH
        if score >= WATCH_AT
        else Verdict.PASS
    )
    return Score(
        opportunity_score=round(score, 2),
        verdict=verdict,
        confidence=round(confidence, 3),
        coverage=round(coverage, 3),
    )
