"""Runtime configuration. Everything is an environment variable (01 §9)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DVANTORA_", env_file=".env", extra="ignore")

    env: str = "local"
    database_url: str = "postgresql://postgres@localhost:5432/dvantora"

    # ADR-0005
    freshness_window_hours: int = 168

    # 07-data-sources.md §8
    run_budget_cents: int = 75

    # Only "fixture" exists. Real vendors are gated on 07 §12 verification.
    collector_mode: str = "fixture"

    # ADR-0004. Only "template" exists.
    ai_provider: str = "template"

    # 02 §3.5 / 05 §5.2 — a market resolves only if the COMBINED (service, location)
    # confidence clears this bar and beats the runner-up by the margin.
    resolution_min_confidence: float = 0.75
    resolution_ambiguity_margin: float = 0.15
    # Below this, the input is not in the taxonomy at all: 422 rather than a
    # 409 shortlist. It only selects which documented error is returned.
    resolution_unknown_floor: float = 0.60

    # 02 §3.6
    run_lease_seconds: int = 900

    # 04-signals-and-scoring.md is not written; these are provisional.
    weights_version: str = "0.0-provisional"
    method_version: str = "0.0-provisional"
    min_coverage_to_score: float = 0.5

    dev_account_email: str = "founder@dvantora.local"


settings = Settings()
