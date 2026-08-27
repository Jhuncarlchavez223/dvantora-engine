"""04-signals-and-scoring.md §3, §5, §6 — the formula, thresholds and gates."""

from __future__ import annotations

import pytest

from engine.enums import SignalBand, SignalKey, Verdict
from engine.signals.normalise import Normalised, unavailable
from engine.signals.score import WEIGHTS, InsufficientEvidence, compute


def n(
    signal: SignalKey,
    score: float,
    conf: float = 0.9,
    band: SignalBand = SignalBand.HIGH,
) -> Normalised:
    return Normalised(
        signal=signal, score=score, band=band, confidence=conf, inputs={}, headline="x"
    )


def all_signals(score: float, conf: float = 0.9) -> list[Normalised]:
    return [n(s, score, conf) for s in SignalKey]


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
    assert set(WEIGHTS) == set(SignalKey)


def test_deterministic():
    assert compute(all_signals(80.0)) == compute(all_signals(80.0))


def test_verdict_thresholds():
    assert compute(all_signals(85.0)).verdict is Verdict.PURSUE
    assert compute(all_signals(70.0)).verdict is Verdict.PURSUE
    assert compute(all_signals(69.9)).verdict is Verdict.WATCH
    assert compute(all_signals(45.0)).verdict is Verdict.WATCH
    assert compute(all_signals(44.9)).verdict is Verdict.PASS


def test_confidence_weighting_pulls_toward_well_evidenced_signals():
    """A high-scoring but low-confidence signal must move the score less (04 §3)."""
    base = [n(s, 50.0, 0.9) for s in SignalKey if s is not SignalKey.CUSTOMER_VALUE]

    confident = compute([*base, n(SignalKey.CUSTOMER_VALUE, 100.0, 0.9)])
    unsure = compute([*base, n(SignalKey.CUSTOMER_VALUE, 100.0, 0.2)])

    assert confident.opportunity_score > unsure.opportunity_score
    assert unsure.confidence < confident.confidence


def test_confidence_is_evidence_weight_over_total_weight():
    perfect = compute(all_signals(60.0, conf=1.0))
    assert perfect.confidence == pytest.approx(1.0)
    assert perfect.coverage == pytest.approx(1.0)


def test_missing_signal_does_not_drag_score_to_zero():
    full = compute(all_signals(80.0))
    partial = compute(
        [n(s, 80.0) for s in SignalKey if s is not SignalKey.DENSITY]
        + [unavailable(SignalKey.DENSITY, "vendor_unavailable")]
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


# --- gates (04 §6) ---------------------------------------------------------


def _strong_except(signal: SignalKey, score: float, **kw) -> list[Normalised]:
    return [n(s, 95.0) if s is not signal else n(s, score, **kw) for s in SignalKey]


def test_g1_demand_floor_caps_at_watch():
    result = compute(_strong_except(SignalKey.DEMAND, 25.0))
    assert result.verdict is Verdict.WATCH
    assert "G1_demand_floor_watch" in result.gates_applied


def test_g1_very_low_demand_forces_pass():
    result = compute(_strong_except(SignalKey.DEMAND, 10.0))
    assert result.verdict is Verdict.PASS
    assert "G1_demand_floor_pass" in result.gates_applied


def test_g2_low_confidence_caps_at_watch():
    result = compute(all_signals(95.0, conf=0.3))
    assert result.confidence < 0.5
    assert result.verdict is Verdict.WATCH
    assert "G2_low_confidence" in result.gates_applied


def test_g3_fires_only_when_both_monetisation_signals_are_absent():
    """An evidence-presence gate: no numeric cutoffs (04 §6)."""
    both_absent = compute(
        [
            n(s, 95.0)
            for s in SignalKey
            if s not in (SignalKey.ADVERTISING, SignalKey.CUSTOMER_VALUE)
        ]
        + [
            unavailable(SignalKey.ADVERTISING, "vendor_unavailable"),
            unavailable(SignalKey.CUSTOMER_VALUE, "no usable CPC reference"),
        ]
    )
    assert both_absent.verdict is Verdict.WATCH
    assert "G3_no_monetisation_evidence" in both_absent.gates_applied

    one_absent = compute(
        [n(s, 95.0) for s in SignalKey if s is not SignalKey.ADVERTISING]
        + [unavailable(SignalKey.ADVERTISING, "vendor_unavailable")]
    )
    assert "G3_no_monetisation_evidence" not in one_absent.gates_applied
    assert one_absent.verdict is Verdict.PURSUE


def test_g4_declining_trend_caps_at_watch():
    signals = [n(s, 95.0) for s in SignalKey if s is not SignalKey.TRENDS]
    signals.append(n(SignalKey.TRENDS, 95.0, band=SignalBand.DECLINING))
    result = compute(signals)
    assert result.verdict is Verdict.WATCH
    assert "G4_declining_trend" in result.gates_applied


def test_gates_never_raise_a_verdict():
    """A weak market with a declining trend stays Pass, not lifted to Watch."""
    signals = [n(s, 20.0) for s in SignalKey if s is not SignalKey.TRENDS]
    signals.append(n(SignalKey.TRENDS, 20.0, band=SignalBand.DECLINING))
    result = compute(signals)
    assert result.verdict is Verdict.PASS


def test_gates_do_not_change_the_score():
    ungated = compute(all_signals(95.0))
    gated_inputs = [n(s, 95.0) for s in SignalKey if s is not SignalKey.TRENDS]
    gated_inputs.append(n(SignalKey.TRENDS, 95.0, band=SignalBand.DECLINING))
    gated = compute(gated_inputs)
    assert gated.opportunity_score == ungated.opportunity_score
    assert gated.verdict is not ungated.verdict
