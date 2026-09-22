"""Google Ads keyword-planning collector helpers."""

from __future__ import annotations

from dataclasses import dataclass

from google.ads.googleads.client import GoogleAdsClient

from engine.config import settings


@dataclass(frozen=True)
class KeywordMetrics:
    keyword: str
    avg_monthly_searches: int
    competition_index: int
    average_cpc: float
    low_top_of_page_bid: float
    high_top_of_page_bid: float


def _client() -> GoogleAdsClient:
    # Build the Google Ads client from Dvantora's local environment settings.
    return GoogleAdsClient.load_from_dict(
        {
            "client_id": settings.google_ads_client_id,
            "client_secret": settings.google_ads_client_secret,
            "refresh_token": settings.google_ads_refresh_token,
            "use_proto_plus": True,
        }
    )


def fetch_keyword_metrics(
    keyword: str,
    geo_target_id: str,
    language_id: str = "1000",
) -> KeywordMetrics:
    # Request historical Keyword Planner metrics from the live Google Ads account.
    client = _client()
    google_ads_service = client.get_service("GoogleAdsService")
    keyword_service = client.get_service("KeywordPlanIdeaService")

    request = client.get_type("GenerateKeywordHistoricalMetricsRequest")
    request.customer_id = settings.google_ads_customer_id
    request.keywords.append(keyword)
    request.geo_target_constants.append(
        google_ads_service.geo_target_constant_path(geo_target_id)
    )
    request.language = google_ads_service.language_constant_path(language_id)
    request.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    request.historical_metrics_options.include_average_cpc = True

    response = keyword_service.generate_keyword_historical_metrics(request=request)

    if not response.results:
        raise ValueError(f"No Google Ads historical metrics returned for {keyword!r}")

    result = response.results[0]
    metrics = result.keyword_metrics

    return KeywordMetrics(
        keyword=result.text,
        avg_monthly_searches=int(metrics.avg_monthly_searches),
        competition_index=int(metrics.competition_index),
        average_cpc=float(metrics.average_cpc_micros) / 1_000_000,
        low_top_of_page_bid=float(metrics.low_top_of_page_bid_micros) / 1_000_000,
        high_top_of_page_bid=float(metrics.high_top_of_page_bid_micros) / 1_000_000,
    )


def fetch_keywords_metrics(
    keywords: list[str],
    geo_target_id: str,
    language_id: str = "1000",
) -> list[KeywordMetrics]:
    """Historical metrics for several keywords in ONE Google Ads request.

    Used by the Customer Value collector to price a trade and its comparison
    basket together. Keywords Google returns no data for are simply absent from
    the result; callers decide what that means. Kept separate from
    fetch_keyword_metrics so the verified live Demand path is unchanged.
    """
    client = _client()
    google_ads_service = client.get_service("GoogleAdsService")
    keyword_service = client.get_service("KeywordPlanIdeaService")

    request = client.get_type("GenerateKeywordHistoricalMetricsRequest")
    request.customer_id = settings.google_ads_customer_id
    request.keywords.extend(keywords)
    request.geo_target_constants.append(
        google_ads_service.geo_target_constant_path(geo_target_id)
    )
    request.language = google_ads_service.language_constant_path(language_id)
    request.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    request.historical_metrics_options.include_average_cpc = True

    response = keyword_service.generate_keyword_historical_metrics(request=request)

    results: list[KeywordMetrics] = []
    for result in response.results:
        metrics = result.keyword_metrics
        results.append(
            KeywordMetrics(
                keyword=result.text,
                avg_monthly_searches=int(metrics.avg_monthly_searches),
                competition_index=int(metrics.competition_index),
                average_cpc=float(metrics.average_cpc_micros) / 1_000_000,
                low_top_of_page_bid=float(metrics.low_top_of_page_bid_micros) / 1_000_000,
                high_top_of_page_bid=float(metrics.high_top_of_page_bid_micros) / 1_000_000,
            )
        )
    return results
