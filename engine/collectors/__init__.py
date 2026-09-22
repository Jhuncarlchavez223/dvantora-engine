from __future__ import annotations

from engine.collectors.base import Collector
from engine.collectors.fixture import FixtureCollector
from engine.collectors.google_ads_demand import GoogleAdsDemandCollector
from engine.config import settings
from engine.enums import SignalKey


def build_collectors() -> list[Collector]:
    if settings.collector_mode == "fixture":
        return [FixtureCollector(signal) for signal in SignalKey]

    if settings.collector_mode == "hybrid":
        return [
            GoogleAdsDemandCollector()
            if signal is SignalKey.DEMAND
            else FixtureCollector(signal)
            for signal in SignalKey
        ]

    raise ValueError(f"Unsupported collector mode: {settings.collector_mode}")