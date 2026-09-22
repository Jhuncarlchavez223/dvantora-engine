from __future__ import annotations

from engine.collectors.base import Collector
from engine.collectors.fixture import FixtureCollector
from engine.collectors.google_ads_demand import GoogleAdsDemandCollector
from engine.collectors.google_ads_value import GoogleAdsCustomerValueCollector
from engine.config import settings
from engine.enums import SignalKey

# Vendor name used by local example data. Anything else is a live source.
FIXTURE_VENDOR = "fixture"


def build_collectors() -> list[Collector]:
    if settings.collector_mode == "fixture":
        return [FixtureCollector(signal) for signal in SignalKey]

    if settings.collector_mode == "hybrid":
        # Live where a verified collector exists; example data everywhere else.
        live: dict[SignalKey, Collector] = {
            SignalKey.DEMAND: GoogleAdsDemandCollector(),
            SignalKey.CUSTOMER_VALUE: GoogleAdsCustomerValueCollector(),
        }
        return [live.get(signal) or FixtureCollector(signal) for signal in SignalKey]

    raise ValueError(f"Unsupported collector mode: {settings.collector_mode}")


def live_sources() -> dict[str, str]:
    """Signals the current mode collects live, mapped to the vendor collecting them.

    Example in hybrid mode: {"demand": "google_ads"}. In fixture mode: {}.

    The freshness check uses this so a recent run is only reused when it was built
    from the same live sources the engine would use now — never an example-data
    run in place of a live one. Building the collector list makes no network calls.
    """
    sources: dict[str, str] = {}
    for collector in build_collectors():
        vendor = getattr(collector, "vendor", FIXTURE_VENDOR)
        if vendor != FIXTURE_VENDOR:
            sources[collector.signal.value] = vendor
    return sources
