"""Advertising activity from Google Ads competition_index (method 1.1).

Every test replaces the Google Ads call with a fake. Nothing here reaches Google.
"""

from __future__ import annotations

import pytest

from engine.collectors import build_collectors
from engine.collectors import google_ads_advertising as adv
from engine.collectors.base import MarketRef
from engine.collectors.google_ads import KeywordMetrics, _optional_int
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


def _fake(ci: int | None):
    def fake(keyword: str, geo_target_id: str, language_id: str = "1000"):
        return KeywordMetrics(
            keyword=keyword,
            avg_monthly_searches=4400,
            competition_index=ci,
            average_cpc=52.48,
            low_top_of_page_bid=13.29,
            high_top_of_page_bid=56.13,
        )

    return fake


def _score(ci: int) -> float:
    result = normalise(SignalKey.ADVERTISING, [{"competition_index": ci}])
    assert result.score is not None
    return result.score


# --- collector -------------------------------------------------------------


def test_collects_competition_index_as_advertising_evidence(monkeypatch):
    monkeypatch.setattr(adv, "fetch_keyword_metrics", _fake(41))
    [result] = adv.GoogleAdsAdvertisingCollector().collect(BRISBANE_PLUMBING)
    assert result.status is EvidenceStatus.OK
    assert result.vendor == "google_ads"
    assert result.signal is SignalKey.ADVERTISING
    assert result.retention_days is None
    assert result.payload["competition_index"] == 41


def test_missing_competition_index_is_unavailable_not_zero(monkeypatch):
    monkeypatch.setattr(adv, "fetch_keyword_metrics", _fake(None))
    [result] = adv.GoogleAdsAdvertisingCollector().collect(BRISBANE_PLUMBING)
    assert result.status is EvidenceStatus.ABSENT
    assert result.payload["reason"] == "no_competition_index"


def test_unmapped_market_never_calls_google(monkeypatch):
    def must_not_call(*args, **kwargs):
        raise AssertionError("Google Ads must not be called for unmapped markets")

    monkeypatch.setattr(adv, "fetch_keyword_metrics", must_not_call)
    richmond = MarketRef(
        market_id="m2",
        market_key="plumbing@au-vic-richmond",
        service_slug="plumbing",
        location_slug="au-vic-richmond",
        display_name="Plumbing — Richmond, VIC",
    )
    [result] = adv.GoogleAdsAdvertisingCollector().collect(richmond)
    assert result.status is EvidenceStatus.ABSENT
    assert result.payload["reason"] == "google_ads_market_not_mapped"


# --- scorer (method 1.1) ----------------------------------------------------


def test_slot_fill_curve_matches_the_approved_table():
    assert _score(0) == pytest.approx(0.0)
    assert _score(41) == pytest.approx(93.52, abs=0.05)
    assert _score(55) == pytest.approx(100.0)
    assert _score(100) == pytest.approx(33.06, abs=0.05)


def test_slot_fill_is_an_inverted_u():
    assert _score(55) > _score(20)
    assert _score(55) > _score(85)


def test_slot_fill_wording_and_confidence_are_honest():
    result = normalise(SignalKey.ADVERTISING, [{"competition_index": 41}])
    assert result.confidence == pytest.approx(0.60)
    assert "Advertiser count" not in result.headline
    assert "not measured" in (result.notes or "")


def test_missing_index_in_payload_is_unavailable():
    result = normalise(SignalKey.ADVERTISING, [{"competition_index": None}])
    assert result.score is None


def test_fixture_advertiser_count_path_is_unchanged():
    result = normalise(
        SignalKey.ADVERTISING, [{"advertiser_count": 14, "advertiser_growth_90d": 0.18}]
    )
    assert result.confidence == pytest.approx(0.70)
    assert result.headline == "Advertiser count rising"


# --- plumbing -----------------------------------------------------------------


class _WithPresence:
    """Stands in for a Google protobuf message that tracks field presence."""

    def __init__(self, **fields: int) -> None:
        self._fields = fields

    def __contains__(self, name: str) -> bool:
        return name in self._fields

    def __getattr__(self, name: str) -> int:
        return self._fields.get(name, 0)


def test_optional_int_keeps_no_data_distinct_from_zero():
    assert _optional_int(_WithPresence(competition_index=41), "competition_index") == 41
    assert _optional_int(_WithPresence(), "competition_index") is None


def test_hybrid_mode_uses_live_advertising(monkeypatch):
    monkeypatch.setattr(settings, "collector_mode", "hybrid")
    by_signal = {c.signal: c for c in build_collectors()}
    assert isinstance(by_signal[SignalKey.ADVERTISING], adv.GoogleAdsAdvertisingCollector)
