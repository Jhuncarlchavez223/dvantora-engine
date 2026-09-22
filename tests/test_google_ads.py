from __future__ import annotations

from decimal import Decimal

from engine.collectors.base import MarketRef
from engine.collectors.google_ads import KeywordMetrics
from engine.collectors.google_ads_demand import GoogleAdsDemandCollector
from engine.enums import EvidenceStatus, SignalKey


def _brisbane_plumbing_market() -> MarketRef:
    # Build the supported Plumbing — Brisbane market used by the collector.
    return MarketRef(
        market_id="test-market",
        market_key="plumbing@au-qld-brisbane",
        service_slug="plumbing",
        location_slug="au-qld-brisbane",
        display_name="Plumbing — Brisbane, QLD",
        population=2570000,
    )


def test_google_ads_demand_collector_maps_live_metrics(monkeypatch) -> None:
    # Replace the real Google Ads request with deterministic fake metrics.
    def fake_fetch_keyword_metrics(
        keyword: str,
        geo_target_id: str,
        language_id: str = "1000",
    ) -> KeywordMetrics:
        assert keyword == "plumber"
        assert geo_target_id == "1000339"
        assert language_id == "1000"

        return KeywordMetrics(
            keyword="plumber",
            avg_monthly_searches=4400,
            competition_index=41,
            average_cpc=52.482951,
            low_top_of_page_bid=13.291251,
            high_top_of_page_bid=56.133716,
        )

    monkeypatch.setattr(
        "engine.collectors.google_ads_demand.fetch_keyword_metrics",
        fake_fetch_keyword_metrics,
    )

    collector = GoogleAdsDemandCollector()
    results = collector.collect(_brisbane_plumbing_market())

    assert len(results) == 1

    result = results[0]

    assert result.signal is SignalKey.DEMAND
    assert result.status is EvidenceStatus.OK
    assert result.vendor == "google_ads"
    assert result.cost_cents == Decimal("0")
    assert result.payload == {
        "monthly_searches": 4400,
        "keyword": "plumber",
        "competition_index": 41,
        "average_cpc": 52.482951,
        "low_top_of_page_bid": 13.291251,
        "high_top_of_page_bid": 56.133716,
    }


def test_google_ads_demand_collector_returns_absent_for_unmapped_market(
    monkeypatch,
) -> None:
    # Fail immediately if an unmapped market ever tries to call Google Ads.
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Google Ads API should not be called")

    monkeypatch.setattr(
        "engine.collectors.google_ads_demand.fetch_keyword_metrics",
        fail_if_called,
    )

    market = MarketRef(
        market_id="test-market",
        market_key="plumbing@au-sa-adelaide",
        service_slug="plumbing",
        location_slug="au-sa-adelaide",
        display_name="Plumbing — Adelaide, SA",
        population=1400000,
    )

    collector = GoogleAdsDemandCollector()
    results = collector.collect(market)

    assert len(results) == 1

    result = results[0]

    assert result.signal is SignalKey.DEMAND
    assert result.status is EvidenceStatus.ABSENT
    assert result.vendor == "google_ads"
    assert result.payload == {"reason": "google_ads_market_not_mapped"}
    assert result.error == "Google Ads keyword or location mapping unavailable"