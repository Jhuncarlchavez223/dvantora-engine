"""Customer Value collector (Google Ads CPC vs basket median).

Every test replaces the Google Ads call with a fake. Nothing here reaches Google.
"""

from __future__ import annotations

import statistics

import pytest

from engine.collectors import build_collectors
from engine.collectors import google_ads_value as value
from engine.collectors.base import MarketRef
from engine.collectors.google_ads import KeywordMetrics
from engine.config import settings
from engine.enums import EvidenceStatus, SignalKey
from engine.signals.normalise import normalise

BRISBANE_PLUMBING = MarketRef(
    market_id="m1",
    market_key="plumbing@au-qld-brisbane",
    service_slug="plumbing",
    location_slug="au-qld-brisbane",
    display_name="Plumbing — Brisbane, QLD",
    population=2_568_900,
)

# Fake basket prices (AUD). Illustrative test values, not real market data.
BASKET_CPCS = {
    "electrician": 30.0,
    "carpenter": 12.0,
    "painter": 10.0,
    "roofer": 25.0,
    "landscaper": 8.0,
    "house cleaning": 6.0,
    "pest control": 14.0,
    "locksmith": 40.0,
    "air conditioning repair": 20.0,
    "concreter": 11.0,
    "tiler": 9.0,
}


def _metrics(keyword: str, cpc: float) -> KeywordMetrics:
    return KeywordMetrics(
        keyword=keyword,
        avg_monthly_searches=1000,
        competition_index=50,
        average_cpc=cpc,
        low_top_of_page_bid=cpc / 2,
        high_top_of_page_bid=cpc * 2,
    )


def _fake_fetch(prices: dict[str, float], calls: list[list[str]]):
    def fake(keywords: list[str], geo_target_id: str, language_id: str = "1000"):
        calls.append(list(keywords))
        return [_metrics(k, prices[k]) for k in keywords if k in prices]

    return fake


def test_prices_trade_against_basket_median_in_one_request(monkeypatch):
    calls: list[list[str]] = []
    prices = {"plumber": 52.48, **BASKET_CPCS}
    monkeypatch.setattr(value, "fetch_keywords_metrics", _fake_fetch(prices, calls))

    [result] = value.GoogleAdsCustomerValueCollector().collect(BRISBANE_PLUMBING)

    assert len(calls) == 1  # trade + basket priced together
    assert result.status is EvidenceStatus.OK
    assert result.vendor == "google_ads"
    assert result.retention_days is None  # aggregates only
    p = result.payload
    assert p["cpc"] == 52.48
    assert p["cpc_basket_median"] == statistics.median(BASKET_CPCS.values())
    assert p["basket_version"] == "v1"
    assert p["basket_size"] == 11


def test_trade_is_excluded_from_its_own_basket(monkeypatch):
    calls: list[list[str]] = []
    prices = {"plumber": 52.48, **BASKET_CPCS}
    monkeypatch.setattr(value, "fetch_keywords_metrics", _fake_fetch(prices, calls))

    [result] = value.GoogleAdsCustomerValueCollector().collect(BRISBANE_PLUMBING)

    basket_keywords = [b["keyword"] for b in result.payload["basket"]]
    assert "plumber" not in basket_keywords
    assert calls[0].count("plumber") == 1  # requested once, as the trade itself


def test_unmapped_market_never_calls_google(monkeypatch):
    def must_not_call(*args, **kwargs):
        raise AssertionError("Google Ads must not be called for unmapped markets")

    monkeypatch.setattr(value, "fetch_keywords_metrics", must_not_call)
    richmond = MarketRef(
        market_id="m2",
        market_key="plumbing@au-vic-richmond",
        service_slug="plumbing",
        location_slug="au-vic-richmond",
        display_name="Plumbing — Richmond, VIC",
    )
    [result] = value.GoogleAdsCustomerValueCollector().collect(richmond)
    assert result.status is EvidenceStatus.ABSENT
    assert result.payload["reason"] == "google_ads_market_not_mapped"


def test_too_few_priced_basket_trades_is_unavailable(monkeypatch):
    thin = {"plumber": 52.48, "electrician": 30.0, "roofer": 25.0}  # only 2 basket prices
    monkeypatch.setattr(value, "fetch_keywords_metrics", _fake_fetch(thin, []))

    [result] = value.GoogleAdsCustomerValueCollector().collect(BRISBANE_PLUMBING)
    assert result.status is EvidenceStatus.ABSENT
    assert result.payload["reason"] == "cpc_basket_too_small"
    assert result.payload["basket_size"] == 2


def test_trade_without_a_price_is_unavailable(monkeypatch):
    prices = {"plumber": 0.0, **BASKET_CPCS}
    monkeypatch.setattr(value, "fetch_keywords_metrics", _fake_fetch(prices, []))

    [result] = value.GoogleAdsCustomerValueCollector().collect(BRISBANE_PLUMBING)
    assert result.status is EvidenceStatus.ABSENT
    assert result.payload["reason"] == "no_cpc_for_service"


def test_payload_feeds_the_existing_scorer_unchanged(monkeypatch):
    prices = {"plumber": 52.48, **BASKET_CPCS}
    monkeypatch.setattr(value, "fetch_keywords_metrics", _fake_fetch(prices, []))
    [result] = value.GoogleAdsCustomerValueCollector().collect(BRISBANE_PLUMBING)

    scored = normalise(SignalKey.CUSTOMER_VALUE, [result.payload])
    assert scored.score is not None
    assert scored.confidence == pytest.approx(0.45)  # cap unchanged (07 §6.5)


def test_hybrid_mode_uses_live_customer_value(monkeypatch):
    # Building the list makes no network calls.
    monkeypatch.setattr(settings, "collector_mode", "hybrid")
    by_signal = {c.signal: c for c in build_collectors()}
    assert isinstance(
        by_signal[SignalKey.CUSTOMER_VALUE], value.GoogleAdsCustomerValueCollector
    )
