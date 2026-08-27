"""Scoring is deterministic and must never invent a score (00 §5)."""

from __future__ import annotations

import pytest

from engine.enums import SignalBand, SignalKey, Verdict
from engine.signals.normalise import Normalised, unavailable
from engine.signals.score import InsufficientEvidence, compute


def n(signal: SignalKey, score: float, conf: float = 0.9) -> Normalised:
    return Normalised(
        signal=signal, score=score, band=SignalBand.HIGH, confidence=conf, inputs={}, headline="x"
    )


def all_signals(score: float) -> list[Normalised]:
    return [n(s, score) for s in SignalKey]


def test_deterministic():
    a = compute(all_signals(80.0))
    b = compute(all_signals(80.0))
    assert a == b


def test_verdict_thresholds():
    assert compute(all_signals(85.0)).verdict is Verdict.PURSUE
    assert compute(all_signals(55.0)).verdict is Verdict.WATCH
    assert compute(all_signals(20.0)).verdict is Verdict.PASS


def test_missing_signal_does_not_drag_score_to_zero():
    """Weights are renormalised over available signals."""
    full = compute(all_signals(80.0))
    partial = compute(
        [n(s, 80.0) for s in SignalKey if s is not SignalKey.TRENDS]
        + [unavailable(SignalKey.TRENDS, "vendor_unavailable")]
    )
    assert partial.opportunity_score == pytest.approx(full.opportunity_score)
    assert partial.coverage < full.coverage
    assert partial.confidence < full.confidence


def test_insufficient_evidence_refuses_to_score():
    with pytest.raises(InsufficientEvidence):
        compute(
            [n(SignalKey.DEMAND, 90.0)]
            + [unavailable(s, "no fixture") for s in SignalKey if s is not SignalKey.DEMAND]
        )


def test_all_absent_refuses_to_score():
    with pytest.raises(InsufficientEvidence):
        compute([unavailable(s, "no fixture") for s in SignalKey])
