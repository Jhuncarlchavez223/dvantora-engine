"""04-signals-and-scoring.md §4 — the normalisation curves."""

from __future__ import annotations

import pytest

from engine.enums import SignalBand, SignalKey
from engine.signals.normalise import normalise, unavailable


def s(signal: SignalKey, payload: dict, **kw) -> float:
    result = normalise(signal, [payload], **kw)
    assert result.score is not None
    return result.score


# --- demand (§4.1) ---------------------------------------------------------


def test_demand_is_logarithmic_and_bounded():
    assert s(SignalKey.DEMAND, {"monthly_searches": 50}) == 0.0
    assert s(SignalKey.DEMAND, {"monthly_searches": 100_000}) == 100.0
    low = s(SignalKey.DEMAND, {"monthly_searches": 1_000})
    high = s(SignalKey.DEMAND, {"monthly_searches": 10_000})
    assert 0 < low < high < 100
    # A tenfold step is worth the same wherever it happens on the curve.
    step_a = s(SignalKey.DEMAND, {"monthly_searches": 1_000}) - s(
        SignalKey.DEMAND, {"monthly_searches": 100}
    )
    step_b = s(SignalKey.DEMAND, {"monthly_searches": 10_000}) - s(
        SignalKey.DEMAND, {"monthly_searches": 1_000}
    )
    assert step_a == pytest.approx(step_b, abs=0.01)


# --- competition (§4.2) ----------------------------------------------------


def test_competition_higher_score_means_easier_entry():
    easy = s(
        SignalKey.COMPETITION, {"aggregator_share": 0.05, "paid_slots": 0, "distinct_domains": 10}
    )
    hard = s(
        SignalKey.COMPETITION, {"aggregator_share": 0.90, "paid_slots": 4, "distinct_domains": 3}
    )
    assert easy > hard
    assert easy > 80 and hard < 30


def test_aggregator_dominance_outweighs_paid_slots():
    """Directory dominance is the barrier money cannot easily solve."""
    aggregators = s(
        SignalKey.COMPETITION, {"aggregator_share": 1.0, "paid_slots": 0, "distinct_domains": 10}
    )
    ads = s(
        SignalKey.COMPETITION, {"aggregator_share": 0.0, "paid_slots": 4, "distinct_domains": 10}
    )
    assert aggregators < ads


# --- advertising (§4.3) — the inverted U -----------------------------------


def test_advertising_is_an_inverted_u_not_monotonic():
    """Zero advertisers is not a free win; a saturated field is not attractive."""
    none = s(SignalKey.ADVERTISING, {"advertiser_count": 0, "advertiser_growth_90d": 0})
    healthy = s(SignalKey.ADVERTISING, {"advertiser_count": 12, "advertiser_growth_90d": 0})
    saturated = s(SignalKey.ADVERTISING, {"advertiser_count": 60, "advertiser_growth_90d": 0})
    assert healthy > none
    assert healthy > saturated


def test_advertising_zero_is_flagged_as_possibly_unmonetised():
    result = normalise(SignalKey.ADVERTISING, [{"advertiser_count": 0}])
    assert result.notes is not None
    assert "monetise" in result.notes


def test_advertising_momentum_is_bounded():
    flat = s(SignalKey.ADVERTISING, {"advertiser_count": 12, "advertiser_growth_90d": 0.0})
    surging = s(SignalKey.ADVERTISING, {"advertiser_count": 12, "advertiser_growth_90d": 5.0})
    assert 0 < surging - flat <= 15.0


def test_advertising_band_follows_growth():
    up = normalise(SignalKey.ADVERTISING, [{"advertiser_count": 12, "advertiser_growth_90d": 0.2}])
    down = normalise(
        SignalKey.ADVERTISING, [{"advertiser_count": 12, "advertiser_growth_90d": -0.2}]
    )
    assert up.band is SignalBand.GROWING
    assert down.band is SignalBand.DECLINING


# --- density (§4.4) --------------------------------------------------------


def test_density_saturates_rather_than_growing_without_bound():
    payload = {"business_count": 200}
    mid = s(SignalKey.DENSITY, payload, population=100_000)
    lots = s(SignalKey.DENSITY, {"business_count": 2_000}, population=100_000)
    assert mid < lots < 100


def test_density_prefers_per_capita_and_records_the_basis():
    with_pop = normalise(SignalKey.DENSITY, [{"business_count": 128}], population=2_568_900)
    without = normalise(SignalKey.DENSITY, [{"business_count": 128}], population=None)
    assert with_pop.inputs["basis"] == "per_capita"
    assert without.inputs["basis"] == "absolute_count"
    assert without.confidence < with_pop.confidence
    assert "sample" in (with_pop.notes or "")


# --- customer value (§4.5) -------------------------------------------------


def test_customer_value_is_relative_to_the_basket():
    at_basket = s(SignalKey.CUSTOMER_VALUE, {"cpc": 7.0, "cpc_basket_median": 7.0})
    assert at_basket == pytest.approx(50.0, abs=0.01)
    assert s(SignalKey.CUSTOMER_VALUE, {"cpc": 14.0, "cpc_basket_median": 7.0}) > at_basket
    assert s(SignalKey.CUSTOMER_VALUE, {"cpc": 3.5, "cpc_basket_median": 7.0}) < at_basket


def test_customer_value_confidence_is_capped():
    """07 §6.5 — structurally the weakest signal."""
    result = normalise(SignalKey.CUSTOMER_VALUE, [{"cpc": 12.4, "cpc_basket_median": 7.1}])
    assert result.confidence <= 0.45
    assert "not a measured figure" in (result.notes or "")


def test_customer_value_without_a_cpc_reference_is_unavailable():
    result = normalise(SignalKey.CUSTOMER_VALUE, [{"cpc": 0, "cpc_basket_median": 0}])
    assert result.score is None
    assert result.band is SignalBand.UNKNOWN


# --- trends (§4.6) ---------------------------------------------------------


def test_trend_slope_maps_around_fifty():
    assert s(SignalKey.TRENDS, {"yoy_slope": 0.0, "granularity": "city"}) == pytest.approx(50.0)
    assert s(SignalKey.TRENDS, {"yoy_slope": 0.25, "granularity": "city"}) == 100.0
    assert s(SignalKey.TRENDS, {"yoy_slope": -0.25, "granularity": "city"}) == 0.0


def test_coarser_granularity_reduces_confidence_and_says_so():
    city = normalise(
        SignalKey.TRENDS, [{"yoy_slope": 0.1, "granularity": "city"}], market_granularity="city"
    )
    state = normalise(
        SignalKey.TRENDS, [{"yoy_slope": 0.1, "granularity": "admin1"}], market_granularity="city"
    )
    country = normalise(
        SignalKey.TRENDS, [{"yoy_slope": 0.1, "granularity": "country"}], market_granularity="city"
    )
    assert city.confidence > state.confidence > country.confidence
    assert city.score == state.score == country.score  # penalty is on confidence only
    assert "coarser than the market" in (state.notes or "")


# --- absence ---------------------------------------------------------------


def test_no_payload_yields_an_explicit_unavailable_signal():
    for signal in SignalKey:
        result = normalise(signal, [])
        assert result.score is None
        assert result.confidence == 0.0
        assert result.band is SignalBand.UNKNOWN
        assert "unavailable" in (result.notes or "").lower()


def test_unavailable_records_the_reason():
    assert "vendor_unavailable" in (unavailable(SignalKey.DEMAND, "vendor_unavailable").notes or "")


def test_trend_headline_matches_its_band():
    up = normalise(SignalKey.TRENDS, [{"yoy_slope": 0.2, "granularity": "city"}])
    down = normalise(SignalKey.TRENDS, [{"yoy_slope": -0.2, "granularity": "city"}])
    flat = normalise(SignalKey.TRENDS, [{"yoy_slope": 0.0, "granularity": "city"}])
    assert (up.band, up.headline) == (SignalBand.GROWING, "Interest trending up")
    assert (down.band, down.headline) == (SignalBand.DECLINING, "Interest declining")
    assert (flat.band, flat.headline) == (SignalBand.MODERATE, "Interest broadly flat")


def test_trend_note_uses_plain_words_not_admin1():
    result = normalise(
        SignalKey.TRENDS, [{"yoy_slope": 0.1, "granularity": "admin1"}], market_granularity="city"
    )
    assert "state level" in (result.notes or "")
    assert "admin1" not in (result.notes or "")
    assert result.inputs["granularity"] == "admin1"  # stored code unchanged
