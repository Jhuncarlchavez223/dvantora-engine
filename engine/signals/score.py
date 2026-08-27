"""Composite scoring and verdict (04-signals-and-scoring.md §2, §3, §5, §6).

Deterministic: no network, no model calls. v1.0 starting priors — recalibrate after
~30 real market runs (04 §8).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.config import settings
from engine.enums import SignalBand, SignalKey, Verdict
from engine.signals.normalise import Normalised

# 04 §2 — importance weights, summing to 1.00
WEIGHTS: dict[SignalKey, float] = {
    SignalKey.DEMAND: 0.25,
    SignalKey.COMPETITION: 0.20,
    SignalKey.CUSTOMER_VALUE: 0.20,
    SignalKey.DENSITY: 0.15,
    SignalKey.ADVERTISING: 0.10,
    SignalKey.TRENDS: 0.10,
}

# 04 §5 — thresholds
PURSUE_AT = 70.0
WATCH_AT = 45.0

# 04 §6 — gates
DEMAND_CAP_FLOOR = 30.0
DEMAND_PASS_FLOOR = 15.0
CONFIDENCE_GATE = 0.50

_VERDICT_RANK: dict[Verdict, int] = {Verdict.PASS: 0, Verdict.WATCH: 1, Verdict.PURSUE: 2}


@dataclass(frozen=True)
class Score:
    opportunity_score: float
    verdict: Verdict
    confidence: float
    coverage: float
    gates_applied: tuple[str, ...] = field(default_factory=tuple)
    weights_version: str = settings.weights_version


class InsufficientEvidence(Exception):
    """Too little evidence to score honestly (00 §5, 04 §3)."""

    def __init__(self, coverage: float) -> None:
        super().__init__(f"coverage {coverage:.2f} below minimum")
        self.coverage = coverage


def _cap(verdict: Verdict, ceiling: Verdict) -> Verdict:
    """Gates only ever lower a verdict (04 §6)."""
    return verdict if _VERDICT_RANK[verdict] <= _VERDICT_RANK[ceiling] else ceiling


def _apply_gates(
    verdict: Verdict, by_signal: dict[SignalKey, Normalised], confidence: float
) -> tuple[Verdict, tuple[str, ...]]:
    applied: list[str] = []

    # G1 — demand floor. No volume, no business.
    demand = by_signal.get(SignalKey.DEMAND)
    if demand is not None and demand.score is not None:
        if demand.score < DEMAND_PASS_FLOOR:
            verdict = _cap(verdict, Verdict.PASS)
            applied.append("G1_demand_floor_pass")
        elif demand.score < DEMAND_CAP_FLOOR:
            verdict = _cap(verdict, Verdict.WATCH)
            applied.append("G1_demand_floor_watch")

    # G2 — cannot recommend Pursue on thin evidence (00 §6).
    if confidence < CONFIDENCE_GATE:
        verdict = _cap(verdict, Verdict.WATCH)
        applied.append("G2_low_confidence")

    # G3 — monetisation evidence. Deliberately about the ABSENCE of evidence, with no
    # numeric cutoffs: any threshold on advertiser counts or CPC would be invented
    # rather than derived. A calibrated numeric form may follow real runs (04 §6).
    advertising = by_signal.get(SignalKey.ADVERTISING)
    value = by_signal.get(SignalKey.CUSTOMER_VALUE)
    advertising_absent = advertising is None or advertising.score is None
    value_absent = value is None or value.score is None
    if advertising_absent and value_absent:
        verdict = _cap(verdict, Verdict.WATCH)
        applied.append("G3_no_monetisation_evidence")

    # G4 — a healthy snapshot of a shrinking market is a trap.
    trends = by_signal.get(SignalKey.TRENDS)
    if trends is not None and trends.band is SignalBand.DECLINING:
        verdict = _cap(verdict, Verdict.WATCH)
        applied.append("G4_declining_trend")

    return verdict, tuple(applied)


def compute(normalised: list[Normalised]) -> Score:
    by_signal = {n.signal: n for n in normalised}
    available = [n for n in normalised if n.score is not None]

    total_weight = sum(WEIGHTS.values())
    covered_weight = sum(WEIGHTS[n.signal] for n in available)
    coverage = covered_weight / total_weight if total_weight else 0.0

    if coverage < settings.min_coverage_to_score:
        raise InsufficientEvidence(coverage)

    # 04 §3 — contribution is importance x confidence, renormalised over what exists.
    evidence_weight = sum(WEIGHTS[n.signal] * n.confidence for n in available)
    if evidence_weight <= 0:
        raise InsufficientEvidence(coverage)

    # Round BEFORE thresholding: the verdict must be derived from the same number the
    # report displays, or a report can show exactly 70.0 and say "Watch".
    score = round(
        sum((n.score or 0.0) * WEIGHTS[n.signal] * n.confidence for n in available)
        / evidence_weight,
        2,
    )
    confidence = round(evidence_weight / total_weight, 3)

    base_verdict = (
        Verdict.PURSUE
        if score >= PURSUE_AT
        else Verdict.WATCH
        if score >= WATCH_AT
        else Verdict.PASS
    )
    verdict, gates = _apply_gates(base_verdict, by_signal, confidence)

    return Score(
        opportunity_score=score,
        verdict=verdict,
        confidence=confidence,
        coverage=round(coverage, 3),
        gates_applied=gates,
    )
