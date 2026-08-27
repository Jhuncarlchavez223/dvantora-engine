"""Deterministic, no-model analysis writer.

Two jobs at once (ADR-0004): it proves the provider abstraction before a cent is
spent, and it is the fallback the architecture already requires when a model
returns schema-invalid output. It makes no network calls.

Every sentence is assembled from values passed in — it cannot invent a number,
which is the property 00 §7 requires of any generated text.
"""

from __future__ import annotations

from engine.ai.provider import AnalysisRequest, AnalysisResult
from engine.enums import ReportGenerator

PROMPT_VERSION = "template-0.1"


class TemplateProvider:
    name = "template"

    def analyse(self, request: AnalysisRequest) -> AnalysisResult:
        ranked = sorted(
            (s for s in request.signals if s.get("score") is not None),
            key=lambda s: s["score"],
            reverse=True,
        )

        reasons = [
            {
                "n": i + 1,
                "title": s["headline"],
                "body": (
                    f"{s['signal'].replace('_', ' ').capitalize()} scored "
                    f"{s['score']:.0f} of 100 ({s['band']}), with confidence "
                    f"{s['confidence']:.2f}."
                ),
            }
            for i, s in enumerate(ranked[:4])
        ]

        summary = (
            f"{request.market_display_name} scores {request.opportunity_score:.0f} of 100 "
            f"with overall confidence {request.confidence:.2f}. "
            f"The strongest signal is {ranked[0]['signal'].replace('_', ' ')} "
            f"({ranked[0]['score']:.0f}); the weakest is "
            f"{ranked[-1]['signal'].replace('_', ' ')} ({ranked[-1]['score']:.0f})."
            if ranked
            else f"{request.market_display_name} could not be scored from the available evidence."
        )

        action = {
            "pursue": "Worth pursuing on the evidence collected.",
            "watch": "Worth watching; the evidence is not yet decisive.",
            "pass": "Not attractive on the evidence collected.",
        }.get(request.verdict, "No recommendation available.")

        caveats = [
            "Generated without a language model (template provider).",
            "Scoring weights are provisional pending 04-signals-and-scoring.md.",
            "Built from local fixture data, not live market measurements.",
        ]
        caveats += [
            f"{s.replace('_', ' ').capitalize()} could not be collected for this run."
            for s in request.missing_signals
        ]

        return AnalysisResult(
            summary=summary,
            reasons=reasons,
            recommended_action=action,
            caveats=caveats,
            generator=ReportGenerator.TEMPLATE,
            provider=None,
            model=None,
            prompt_version=PROMPT_VERSION,
        )
