"""Google Ads collector for the Advertising activity signal (04 §4.3, method 1.1).

Uses Keyword Planner's competition_index: "how competitive ad placement is for a
keyword ... the number of ad slots filled divided by the total number of ad slots
available", 0-100. It measures how full the ad space is — not how many
advertisers there are, and not whether that is growing. The scorer and report
say so.

Assigned to Advertising activity, not Competition, per 07-data-sources.md §3.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

from engine.collectors.base import Collector, CollectorResult, MarketRef
from engine.collectors.google_ads import fetch_keyword_metrics
from engine.collectors.google_ads_demand import GEO_TARGETS, SERVICE_KEYWORDS
from engine.enums import EvidenceStatus, SignalKey

ENDPOINT = "KeywordPlanIdeaService.GenerateKeywordHistoricalMetrics"


def _hash(*parts: str) -> str:
    # Stable request identifier built only from non-secret request details.
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


class GoogleAdsAdvertisingCollector(Collector):
    signal = SignalKey.ADVERTISING
    name = "google_ads.advertising"
    vendor = "google_ads"

    def _absent(self, request_hash: str, reason: str) -> CollectorResult:
        return CollectorResult(
            signal=self.signal,
            status=EvidenceStatus.ABSENT,
            vendor=self.vendor,
            endpoint=ENDPOINT,
            request_hash=request_hash,
            payload={"reason": reason},
            error=reason,
        )

    def collect(self, market: MarketRef) -> list[CollectorResult]:
        keyword = SERVICE_KEYWORDS.get(market.service_slug)
        geo_target_id = GEO_TARGETS.get(market.location_slug)

        if keyword is None or geo_target_id is None:
            # Unsupported market: never call Google.
            return [
                self._absent(
                    _hash(self.vendor, "advertising", market.service_slug, market.location_slug),
                    "google_ads_market_not_mapped",
                )
            ]

        request_hash = _hash(self.vendor, "advertising", keyword, geo_target_id)
        metrics = fetch_keyword_metrics(keyword, geo_target_id)

        if metrics.competition_index is None:
            # Google had too little data. Unavailable, never a misleading 0.
            return [self._absent(request_hash, "no_competition_index")]

        return [
            CollectorResult(
                signal=self.signal,
                status=EvidenceStatus.OK,
                vendor=self.vendor,
                endpoint=ENDPOINT,
                request_hash=request_hash,
                payload={
                    "competition_index": metrics.competition_index,
                    "keyword": keyword,
                    "measure": "ad_slot_fill",
                },
                cost_cents=Decimal("0"),
            )
        ]
