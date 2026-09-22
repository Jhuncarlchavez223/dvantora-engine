"""Google Ads collector for the Demand signal."""

from __future__ import annotations

import hashlib
from decimal import Decimal

from engine.collectors.base import Collector, CollectorResult, MarketRef
from engine.collectors.google_ads import fetch_keyword_metrics
from engine.enums import EvidenceStatus, SignalKey

# Initial production mappings for Dvantora's currently supported markets.
SERVICE_KEYWORDS = {
    "plumbing": "plumber",
    "electrical": "electrician",
}

GEO_TARGETS = {
    "au-qld-brisbane": "1000339",
}


def _hash(*parts: str) -> str:
    # Produce a stable request identifier without storing credentials.
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


class GoogleAdsDemandCollector(Collector):
    signal = SignalKey.DEMAND
    name = "google_ads.demand"
    vendor = "google_ads"

    def collect(self, market: MarketRef) -> list[CollectorResult]:
        keyword = SERVICE_KEYWORDS.get(market.service_slug)
        geo_target_id = GEO_TARGETS.get(market.location_slug)

        if keyword is None or geo_target_id is None:
            return [
                CollectorResult(
                    signal=self.signal,
                    status=EvidenceStatus.ABSENT,
                    vendor=self.vendor,
                    endpoint="KeywordPlanIdeaService.GenerateKeywordHistoricalMetrics",
                    request_hash=_hash(
                        self.vendor,
                        market.service_slug,
                        market.location_slug,
                    ),
                    payload={"reason": "google_ads_market_not_mapped"},
                    error="Google Ads keyword or location mapping unavailable",
                )
            ]

        metrics = fetch_keyword_metrics(keyword, geo_target_id)

        return [
            CollectorResult(
                signal=self.signal,
                status=EvidenceStatus.OK,
                vendor=self.vendor,
                endpoint="KeywordPlanIdeaService.GenerateKeywordHistoricalMetrics",
                request_hash=_hash(
                    self.vendor,
                    keyword,
                    geo_target_id,
                ),
                payload={
                    "monthly_searches": metrics.avg_monthly_searches,
                    "keyword": metrics.keyword,
                    "competition_index": metrics.competition_index,
                    "average_cpc": metrics.average_cpc,
                    "low_top_of_page_bid": metrics.low_top_of_page_bid,
                    "high_top_of_page_bid": metrics.high_top_of_page_bid,
                },
                cost_cents=Decimal("0"),
            )
        ]