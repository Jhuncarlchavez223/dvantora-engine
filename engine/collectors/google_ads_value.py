"""Google Ads collector for the Customer Value signal (04 §4.5).

Customer Value compares what advertisers pay per click for this trade against
the median of a fixed basket of other local trades in the same location. The
ratio is a proxy for how much a job is worth: advertisers bid roughly in line
with what a customer is worth to them. It also reflects advertiser competition,
which is why the scorer caps this signal's confidence (07 §6.5).

The trade and its whole basket are priced in ONE Google Ads request.
"""

from __future__ import annotations

import hashlib
import statistics
from decimal import Decimal

from engine.collectors.base import Collector, CollectorResult, MarketRef
from engine.collectors.google_ads import fetch_keywords_metrics
from engine.collectors.google_ads_demand import GEO_TARGETS, SERVICE_KEYWORDS
from engine.enums import EvidenceStatus, SignalKey

# Comparison basket, version 1 (approved 2026-09-23). Changing this list changes
# every Customer Value score, so bump BASKET_VERSION whenever it changes; the
# version is stored with each piece of evidence.
BASKET_VERSION = "v1"
CPC_BASKET: tuple[str, ...] = (
    "electrician",
    "plumber",
    "carpenter",
    "painter",
    "roofer",
    "landscaper",
    "house cleaning",
    "pest control",
    "locksmith",
    "air conditioning repair",
    "concreter",
    "tiler",
)

# Fewer priced basket trades than this and the median isn't trustworthy.
MIN_BASKET_SIZE = 8

ENDPOINT = "KeywordPlanIdeaService.GenerateKeywordHistoricalMetrics"


def _hash(*parts: str) -> str:
    # Stable request identifier built only from non-secret request details.
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


class GoogleAdsCustomerValueCollector(Collector):
    signal = SignalKey.CUSTOMER_VALUE
    name = "google_ads.customer_value"
    vendor = "google_ads"

    def _absent(self, request_hash: str, reason: str, **extra: object) -> CollectorResult:
        return CollectorResult(
            signal=self.signal,
            status=EvidenceStatus.ABSENT,
            vendor=self.vendor,
            endpoint=ENDPOINT,
            request_hash=request_hash,
            payload={"reason": reason, **extra},
            error=reason,
        )

    def collect(self, market: MarketRef) -> list[CollectorResult]:
        keyword = SERVICE_KEYWORDS.get(market.service_slug)
        geo_target_id = GEO_TARGETS.get(market.location_slug)

        if keyword is None or geo_target_id is None:
            # Unsupported market: never call Google.
            return [
                self._absent(
                    _hash(self.vendor, "value", market.service_slug, market.location_slug),
                    "google_ads_market_not_mapped",
                )
            ]

        # The trade is compared against the OTHER trades, never partly itself.
        basket = [k for k in CPC_BASKET if k != keyword]
        request_hash = _hash(self.vendor, "value", BASKET_VERSION, keyword, geo_target_id)

        metrics = fetch_keywords_metrics([keyword, *basket], geo_target_id)
        by_keyword = {m.keyword.strip().lower(): m for m in metrics}

        target = by_keyword.get(keyword)
        if target is None or target.average_cpc <= 0:
            return [self._absent(request_hash, "no_cpc_for_service", keyword=keyword)]

        priced = [
            {"keyword": k, "average_cpc": by_keyword[k].average_cpc}
            for k in basket
            if k in by_keyword and by_keyword[k].average_cpc > 0
        ]
        if len(priced) < MIN_BASKET_SIZE:
            return [
                self._absent(
                    request_hash,
                    "cpc_basket_too_small",
                    basket_size=len(priced),
                    min_basket_size=MIN_BASKET_SIZE,
                )
            ]

        median = statistics.median(p["average_cpc"] for p in priced)

        return [
            CollectorResult(
                signal=self.signal,
                status=EvidenceStatus.OK,
                vendor=self.vendor,
                endpoint=ENDPOINT,
                request_hash=request_hash,
                # Aggregates only — no business identities — so no retention limit.
                payload={
                    "cpc": target.average_cpc,
                    "cpc_basket_median": round(median, 6),
                    "keyword": keyword,
                    "basket_version": BASKET_VERSION,
                    "basket_size": len(priced),
                    "basket": priced,
                },
                cost_cents=Decimal("0"),
            )
        ]
