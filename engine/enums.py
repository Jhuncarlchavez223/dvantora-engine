"""Mirrors the enumerated types in 02-data-model.md §4. Values must match the DB."""

from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    COLLECTING = "collecting"
    SCORING = "scoring"
    ANALYZING = "analyzing"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {RunStatus.COMPLETE, RunStatus.PARTIAL, RunStatus.FAILED, RunStatus.CANCELLED}
ACTIVE_STATUSES = {RunStatus.QUEUED, RunStatus.COLLECTING, RunStatus.SCORING, RunStatus.ANALYZING}


class RunStage(StrEnum):
    RESOLVE = "resolve"
    COLLECT_DEMAND = "collect_demand"
    COLLECT_COMPETITION = "collect_competition"
    COLLECT_ADVERTISING = "collect_advertising"
    COLLECT_DENSITY = "collect_density"
    COLLECT_VALUE = "collect_value"
    COLLECT_TRENDS = "collect_trends"
    SCORE = "score"
    ANALYZE = "analyze"
    FINALIZE = "finalize"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


class SignalKey(StrEnum):
    DEMAND = "demand"
    COMPETITION = "competition"
    ADVERTISING = "advertising"
    DENSITY = "density"
    CUSTOMER_VALUE = "customer_value"
    TRENDS = "trends"


class SignalBand(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    GROWING = "growing"
    DECLINING = "declining"
    UNKNOWN = "unknown"


class Verdict(StrEnum):
    PURSUE = "pursue"
    WATCH = "watch"
    PASS = "pass"


class EvidenceStatus(StrEnum):
    OK = "ok"
    ABSENT = "absent"
    ERROR = "error"


class ReportGenerator(StrEnum):
    LLM = "llm"
    TEMPLATE = "template"


class RunTrigger(StrEnum):
    USER = "user"
    FORCED_REFRESH = "forced_refresh"
    SCHEDULED = "scheduled"
    SYSTEM = "system"


class ResolutionMethod(StrEnum):
    EXACT = "exact"
    ALIAS = "alias"
    FUZZY = "fuzzy"
    MANUAL = "manual"


# 02 §4: the collect_* stage that produces each signal.
SIGNAL_STAGES: dict[SignalKey, RunStage] = {
    SignalKey.DEMAND: RunStage.COLLECT_DEMAND,
    SignalKey.COMPETITION: RunStage.COLLECT_COMPETITION,
    SignalKey.ADVERTISING: RunStage.COLLECT_ADVERTISING,
    SignalKey.DENSITY: RunStage.COLLECT_DENSITY,
    SignalKey.CUSTOMER_VALUE: RunStage.COLLECT_VALUE,
    SignalKey.TRENDS: RunStage.COLLECT_TRENDS,
}

ALL_STAGES: list[RunStage] = list(RunStage)
