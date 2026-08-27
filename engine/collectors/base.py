"""Collector interface (01 §1.5). Every data source implements exactly this."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from engine.enums import EvidenceStatus, SignalKey


@dataclass(frozen=True)
class MarketRef:
    market_id: str
    market_key: str
    service_slug: str
    location_slug: str
    display_name: str
    population: int | None = None


@dataclass(frozen=True)
class CollectorResult:
    """One evidence row.

    `retention_days` is not cosmetic: a non-null value becomes `evidence.expires_at`
    and the row is purged (02 §6). Per-business identity from map sources must set
    it to 30; aggregates leave it None.
    """

    signal: SignalKey
    status: EvidenceStatus
    vendor: str
    endpoint: str
    request_hash: str
    payload: dict[str, Any] = field(default_factory=dict)
    source_url: str | None = None
    cost_cents: Decimal = Decimal("0")
    retention_days: int | None = None
    error: str | None = None


class Collector(Protocol):
    signal: SignalKey
    name: str

    def collect(self, market: MarketRef) -> list[CollectorResult]: ...
