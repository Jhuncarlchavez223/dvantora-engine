"""ADR-0004: the only way the engine reaches a model.

No provider SDK may be imported outside `engine/ai/providers/`. The interface is
structured output against a schema, because that is the capability depended on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from engine.enums import ReportGenerator


@dataclass(frozen=True)
class AnalysisRequest:
    market_display_name: str
    opportunity_score: float
    verdict: str
    confidence: float
    signals: list[dict[str, Any]]
    missing_signals: list[str]


@dataclass(frozen=True)
class AnalysisResult:
    summary: str
    reasons: list[dict[str, Any]]
    recommended_action: str
    caveats: list[str]
    generator: ReportGenerator
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None


class AnalysisProvider(Protocol):
    name: str

    def analyse(self, request: AnalysisRequest) -> AnalysisResult: ...


def get_provider(name: str) -> AnalysisProvider:
    if name == "template":
        from engine.ai.providers.template import TemplateProvider

        return TemplateProvider()
    raise ValueError(
        f"Unknown AI provider {name!r}. Only 'template' is implemented; a model-backed "
        "provider requires approval (no LLM calls in the walking skeleton)."
    )
