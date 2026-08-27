"""Evidence -> a 0-100 sub-score per signal.

PROVISIONAL. `04-signals-and-scoring.md` is not written; the curves here exist to
prove the wiring, not to be the product. Every value carries `method_version` so
a real definition can supersede these without ambiguity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from engine.config import settings
from engine.enums import SignalBand, SignalKey


@dataclass(frozen=True)
class Normalised:
    signal: SignalKey
    score: float | None
    band: SignalBand
    confidence: float
    inputs: dict[str, Any]
    headline: str
    notes: str | None = None
    method_version: str = settings.method_version


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _log_scale(value: float, floor: float, ceiling: float) -> float:
    """Map a count onto 0-100 logarithmically; search volume is not linear in value."""
    if value <= floor:
        return 0.0
    return _clamp(100.0 * math.log(value / floor) / math.log(ceiling / floor))


def _band(score: float, high: float = 66.0, low: float = 34.0) -> SignalBand:
    if score >= high:
        return SignalBand.HIGH
    if score >= low:
        return SignalBand.MODERATE
    return SignalBand.LOW


def _merge(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for p in payloads:
        merged.update(p)
    return merged


def unavailable(signal: SignalKey, reason: str) -> Normalised:
    """05 §6.1 rule 1: a missing signal is present with score None, never omitted."""
    return Normalised(
        signal=signal,
        score=None,
        band=SignalBand.UNKNOWN,
        confidence=0.0,
        inputs={},
        headline=f"{signal.value.replace('_', ' ').capitalize()} unavailable",
        notes=f"Source unavailable during this run ({reason}); excluded from the score.",
    )


def _demand(p: dict[str, Any]) -> Normalised:
    searches = float(p.get("monthly_searches", 0))
    score = _log_scale(searches, floor=100, ceiling=50_000)
    return Normalised(
        signal=SignalKey.DEMAND,
        score=round(score, 2),
        band=_band(score),
        confidence=0.9,
        inputs={"monthly_searches": searches, "seasonality_index": p.get("seasonality_index")},
        headline="Recurring service demand" if score >= 66 else "Moderate service demand",
    )


def _competition(p: dict[str, Any]) -> Normalised:
    """Higher score = easier to enter. Aggregator dominance is the real barrier."""
    aggregator_share = float(p.get("aggregator_share", 0.5))
    paid_slots = float(p.get("paid_slots", 0))
    difficulty = _clamp(100.0 * (0.6 * aggregator_share + 0.4 * min(paid_slots, 4) / 4))
    score = 100.0 - difficulty
    return Normalised(
        signal=SignalKey.COMPETITION,
        score=round(score, 2),
        band=_band(score),
        confidence=0.75,
        inputs={
            "distinct_domains": p.get("distinct_domains"),
            "aggregator_share": aggregator_share,
            "paid_slots": p.get("paid_slots"),
        },
        headline="Auction depth below demand level" if score >= 50 else "Crowded market",
    )


def _advertising(p: dict[str, Any]) -> Normalised:
    count = float(p.get("advertiser_count", 0))
    growth = float(p.get("advertiser_growth_90d", 0.0))
    score = _clamp(_log_scale(count, floor=1, ceiling=60) * 0.7 + _clamp(growth * 200) * 0.3)
    band = (
        SignalBand.GROWING
        if growth > 0.05
        else (SignalBand.DECLINING if growth < -0.05 else _band(score))
    )
    return Normalised(
        signal=SignalKey.ADVERTISING,
        score=round(score, 2),
        band=band,
        confidence=0.7,
        inputs={"advertiser_count": count, "advertiser_growth_90d": growth},
        headline="Advertiser count rising" if growth > 0.05 else "Advertiser count steady",
    )


def _density(p: dict[str, Any], population: int | None) -> Normalised:
    count = float(p.get("business_count", 0))
    per_10k = (count / population * 10_000) if population else None
    score = _log_scale(count, floor=5, ceiling=400)
    notes = None if per_10k is not None else "Per-capita density unavailable: population unknown."
    return Normalised(
        signal=SignalKey.DENSITY,
        score=round(score, 2),
        band=_band(score),
        confidence=0.8,
        inputs={
            "business_count": count,
            "businesses_per_10k": round(per_10k, 3) if per_10k is not None else None,
            "rating_mean": p.get("rating_mean"),
        },
        headline="Deep pool of local businesses" if score >= 66 else "Thin local business base",
        notes=notes,
    )


def _customer_value(p: dict[str, Any]) -> Normalised:
    """Lowest-confidence signal by construction (07 §6.5). Confidence is capped."""
    cpc = float(p.get("cpc", 0))
    basket = float(p.get("cpc_basket_median", 0) or 0)
    ratio = (cpc / basket) if basket else 1.0
    score = _clamp(50.0 * ratio)
    return Normalised(
        signal=SignalKey.CUSTOMER_VALUE,
        score=round(score, 2),
        band=_band(score),
        confidence=0.45,
        inputs={
            "cpc": cpc,
            "cpc_basket_median": basket,
            "cpc_ratio": round(ratio, 3),
            "published_price_low": p.get("published_price_low"),
            "published_price_high": p.get("published_price_high"),
        },
        headline="High average job values" if score >= 66 else "Moderate job values",
        notes=(
            "Estimated from advertiser bidding behaviour and published pricing, "
            "not a measured figure."
        ),
    )


def _trends(p: dict[str, Any]) -> Normalised:
    slope = float(p.get("yoy_slope", 0.0))
    score = _clamp(50.0 + slope * 200.0)
    band = (
        SignalBand.GROWING
        if slope > 0.03
        else (SignalBand.DECLINING if slope < -0.03 else SignalBand.MODERATE)
    )
    granularity = p.get("granularity", "unknown")
    notes = None
    if granularity != "city":
        notes = f"Measured at {granularity} level; a finer series was unavailable."
    return Normalised(
        signal=SignalKey.TRENDS,
        score=round(score, 2),
        band=band,
        confidence=0.7,
        inputs={"yoy_slope": slope, "granularity": granularity},
        headline="Interest trending up" if slope > 0.03 else "Interest broadly flat",
        notes=notes,
    )


def normalise(
    signal: SignalKey, payloads: list[dict[str, Any]], population: int | None = None
) -> Normalised:
    if not payloads:
        return unavailable(signal, "no evidence")
    p = _merge(payloads)
    if signal is SignalKey.DEMAND:
        return _demand(p)
    if signal is SignalKey.COMPETITION:
        return _competition(p)
    if signal is SignalKey.ADVERTISING:
        return _advertising(p)
    if signal is SignalKey.DENSITY:
        return _density(p, population)
    if signal is SignalKey.CUSTOMER_VALUE:
        return _customer_value(p)
    return _trends(p)
