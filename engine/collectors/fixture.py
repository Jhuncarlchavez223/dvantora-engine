"""Fixture collector — the only collector in the walking skeleton.

Reads local JSON. Makes no network calls of any kind. A market with no fixture
for a signal yields an `absent` evidence row, which is how fail-soft is exercised
without breaking anything (02 §3.8).
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from decimal import Decimal

from engine.collectors.base import Collector, CollectorResult, MarketRef
from engine.enums import EvidenceStatus, SignalKey

FIXTURE_DIR = pathlib.Path(__file__).resolve().parent / "fixtures"


def _hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


class FixtureCollector(Collector):
    vendor = "fixture"

    def __init__(self, signal: SignalKey) -> None:
        self.signal = signal
        self.name = f"fixture.{signal.value}"

    def _path(self, market: MarketRef) -> pathlib.Path:
        return FIXTURE_DIR / market.market_key / f"{self.signal.value}.json"

    def collect(self, market: MarketRef) -> list[CollectorResult]:
        path = self._path(market)
        endpoint = f"fixture://{market.market_key}/{self.signal.value}"
        req = _hash(self.vendor, endpoint)

        if not path.exists():
            return [
                CollectorResult(
                    signal=self.signal,
                    status=EvidenceStatus.ABSENT,
                    vendor=self.vendor,
                    endpoint=endpoint,
                    request_hash=req,
                    payload={"reason": "no_fixture_for_market"},
                    error="no fixture available",
                )
            ]

        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("simulate") == "error":
            return [
                CollectorResult(
                    signal=self.signal,
                    status=EvidenceStatus.ERROR,
                    vendor=self.vendor,
                    endpoint=endpoint,
                    request_hash=req,
                    payload={"reason": raw.get("reason", "simulated_error")},
                    error=raw.get("reason", "simulated error"),
                )
            ]

        results: list[CollectorResult] = []
        for i, part in enumerate(raw["evidence"]):
            results.append(
                CollectorResult(
                    signal=self.signal,
                    status=EvidenceStatus.OK,
                    vendor=self.vendor,
                    endpoint=endpoint,
                    request_hash=_hash(self.vendor, endpoint, str(i)),
                    payload=part["payload"],
                    source_url=part.get("source_url"),
                    cost_cents=Decimal(str(part.get("cost_cents", 0))),
                    retention_days=part.get("retention_days"),
                )
            )
        return results


def build_collectors() -> list[Collector]:
    return [FixtureCollector(s) for s in SignalKey]
