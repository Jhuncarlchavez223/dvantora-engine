"""Evidence -> a 0-100 sub-score per signal.

Implements `04-signals-and-scoring.md` §4. Every curve outputs 0-100 where higher is
more attractive to the buyer — which inverts the plain-language sense of Competition
(a high sub-score means competition is weak).

These are v1.0 starting priors, reasoned from Dvantora's economics rather than fitted
to data. `method_version` is stamped on every row so a recalibration can never
silently change the meaning of a past result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from engine.config import settings
from engine.enums import SignalBand, SignalKey

# --- 04 §4.1 demand ---------------------------------------------------------
DEMAND_FLOOR = 100.0
DEMAND_CEILING = 50_000.0
DEMAND_CONFIDENCE = 0.90

# --- 04 §4.2 competition ----------------------------------------------------
AGGREGATOR_WEIGHT = 0.50
PAID_SLOT_WEIGHT = 0.30
CONCENTRATION_WEIGHT = 0.20
PAID_SLOT_CAP = 4
COMPETITION_CONFIDENCE = 0.75

# --- 04 §4.3 advertising ----------------------------------------------------
ADVERTISER_CEILING = 60.0
ADVERTISING_PEAK = 0.55
MOMENTUM_CAP = 15.0
GROWING_AT = 0.05
ADVERTISING_CONFIDENCE = 0.70

# --- 04 §4.4 density --------------------------------------------------------
DENSITY_HALF_SATURATION = 0.5  # businesses per 10k residents at score 50
DENSITY_FLOOR = 5.0
DENSITY_CEILING = 400.0
DENSITY_CONFIDENCE = 0.80
DENSITY_CONFIDENCE_NO_POPULATION = 0.65

# --- 04 §4.5 customer value -------------------------------------------------
VALUE_MIDPOINT = 50.0
VALUE_SLOPE = 35.0
VALUE_CONFIDENCE_CAP = 0.45  # 07 §6.5 — structurally lower ceiling

# --- 04 §4.6 trends ---------------------------------------------------------
TREND_SLOPE_GAIN = 200.0
TREND_GROWING_AT = 0.03
TREND_CONFIDENCE = 0.70
GRANULARITY_PENALTY: dict[str, float] = {
    "city": 1.00,
    "suburb": 1.00,
    "admin1": 0.80,
    "country": 0.60,
}


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
    score = _log_scale(searches, DEMAND_FLOOR, DEMAND_CEILING)
    return Normalised(
        signal=SignalKey.DEMAND,
        score=round(score, 2),
        band=_band(score),
        confidence=DEMAND_CONFIDENCE,
        inputs={
            "monthly_searches": searches,
            "seasonality_index": p.get("seasonality_index"),
        },
        headline="Recurring service demand" if score >= 66 else "Moderate service demand",
    )


def _competition(p: dict[str, Any]) -> Normalised:
    """Higher score = easier to enter (04 §4.2)."""
    aggregator_share = float(p.get("aggregator_share", 0.5))
    paid_slots = float(p.get("paid_slots", 0))
    distinct_domains = float(p.get("distinct_domains", 10))
    concentration = _clamp(1.0 - distinct_domains / 10.0, 0.0, 1.0)

    difficulty = (
        AGGREGATOR_WEIGHT * aggregator_share
        + PAID_SLOT_WEIGHT * min(paid_slots, PAID_SLOT_CAP) / PAID_SLOT_CAP
        + CONCENTRATION_WEIGHT * concentration
    )
    score = _clamp(100.0 - 100.0 * difficulty)
    return Normalised(
        signal=SignalKey.COMPETITION,
        score=round(score, 2),
        band=_band(score),
        confidence=COMPETITION_CONFIDENCE,
        inputs={
            "distinct_domains": distinct_domains,
            "aggregator_share": aggregator_share,
            "paid_slots": paid_slots,
            "domain_concentration": round(concentration, 3),
        },
        headline=(
            "Auction depth below demand level" if score >= 50 else "Crowded, directory-dominated"
        ),
    )


def _advertising(p: dict[str, Any]) -> Normalised:
    """Inverted U (04 §4.3): zero advertisers is not a free win."""
    count = float(p.get("advertiser_count", 0))
    growth = float(p.get("advertiser_growth_90d", 0.0))

    position = math.log(count + 1.0) / math.log(ADVERTISER_CEILING + 1.0)
    distance = (position - ADVERTISING_PEAK) / ADVERTISING_PEAK
    base = _clamp(100.0 * (1.0 - distance**2))
    momentum = max(-MOMENTUM_CAP, min(MOMENTUM_CAP, growth * 100.0))
    score = _clamp(base + momentum)

    if growth > GROWING_AT:
        band = SignalBand.GROWING
    elif growth < -GROWING_AT:
        band = SignalBand.DECLINING
    else:
        band = _band(score)

    notes = None
    if position > ADVERTISING_PEAK:
        notes = "Advertiser field is crowded; entry cost is likely elevated."
    elif count <= 1:
        notes = "Almost no advertisers — the market may not monetise."

    return Normalised(
        signal=SignalKey.ADVERTISING,
        score=round(score, 2),
        band=band,
        confidence=ADVERTISING_CONFIDENCE,
        inputs={
            "advertiser_count": count,
            "advertiser_growth_90d": growth,
            "log_position": round(position, 3),
        },
        headline=("Advertiser count rising" if growth > GROWING_AT else "Advertiser count steady"),
        notes=notes,
    )


def _density(p: dict[str, Any], population: int | None) -> Normalised:
    """Saturating (04 §4.4). Prefers per-capita; records which path was used."""
    count = float(p.get("business_count", 0))

    if population:
        per_10k = count / population * 10_000.0
        score = 100.0 * per_10k / (per_10k + DENSITY_HALF_SATURATION)
        confidence = DENSITY_CONFIDENCE
        basis = "per_capita"
        notes = (
            "Business count is a sample of map listings, not a census; the per-capita "
            "figure is indicative."
        )
    else:
        per_10k = None
        score = _log_scale(count, DENSITY_FLOOR, DENSITY_CEILING)
        confidence = DENSITY_CONFIDENCE_NO_POPULATION
        basis = "absolute_count"
        notes = "Population unknown; scored on absolute count, less comparable across markets."

    return Normalised(
        signal=SignalKey.DENSITY,
        score=round(_clamp(score), 2),
        band=_band(score),
        confidence=confidence,
        inputs={
            "business_count": count,
            "businesses_per_10k": round(per_10k, 3) if per_10k is not None else None,
            "basis": basis,
            "rating_mean": p.get("rating_mean"),
        },
        headline=("Deep pool of local businesses" if score >= 66 else "Thin local business base"),
        notes=notes,
    )


def _customer_value(p: dict[str, Any]) -> Normalised:
    """Bounded log ratio (04 §4.5). Lowest confidence ceiling in the system."""
    cpc = float(p.get("cpc", 0) or 0)
    basket = float(p.get("cpc_basket_median", 0) or 0)

    if cpc <= 0 or basket <= 0:
        return unavailable(SignalKey.CUSTOMER_VALUE, "no usable CPC reference")

    ratio = cpc / basket
    score = _clamp(VALUE_MIDPOINT + VALUE_SLOPE * math.log2(ratio))
    return Normalised(
        signal=SignalKey.CUSTOMER_VALUE,
        score=round(score, 2),
        band=_band(score),
        confidence=VALUE_CONFIDENCE_CAP,
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


def _trends(p: dict[str, Any], market_granularity: str | None) -> Normalised:
    slope = float(p.get("yoy_slope", 0.0))
    score = _clamp(VALUE_MIDPOINT + slope * TREND_SLOPE_GAIN)

    if slope > TREND_GROWING_AT:
        band = SignalBand.GROWING
    elif slope < -TREND_GROWING_AT:
        band = SignalBand.DECLINING
    else:
        band = SignalBand.MODERATE

    measured_at = str(p.get("granularity", "unknown"))
    penalty = GRANULARITY_PENALTY.get(measured_at, 0.6)
    confidence = round(TREND_CONFIDENCE * penalty, 3)

    notes = f"Trend measured at {measured_at} level."
    if market_granularity and measured_at != market_granularity:
        notes = (
            f"Trend measured at {measured_at} level, coarser than the market "
            f"({market_granularity}); confidence reduced."
        )

    return Normalised(
        signal=SignalKey.TRENDS,
        score=round(score, 2),
        band=band,
        confidence=confidence,
        inputs={"yoy_slope": slope, "granularity": measured_at},
        headline=("Interest trending up" if slope > TREND_GROWING_AT else "Interest broadly flat"),
        notes=notes,
    )


def normalise(
    signal: SignalKey,
    payloads: list[dict[str, Any]],
    population: int | None = None,
    market_granularity: str | None = None,
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
    return _trends(p, market_granularity)
