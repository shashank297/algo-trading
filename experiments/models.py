"""Validated, reproducible experiment definitions."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ExperimentSpec(BaseModel):
    """Everything required to repeat one deterministic strategy evaluation."""

    experiment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    strategy_name: str
    universe: list[str] = Field(min_length=1)
    timeframe: str
    mode: str = "event-driven"
    parameters: dict[str, Any] = Field(default_factory=dict)
    benchmark_symbol: str | None = None
    feature_version: str = "features-v1"
    strategy_version: str = "1.0.0"
    cost_model: dict[str, Any] = Field(default_factory=dict)
    llm_config: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    universe_snapshot_id: str = "CONFIGURED_UNIVERSE"
    fold_id: str | None = None
    cost_model_version: str = "legacy-bps-v1"


class MassExperimentSpec(BaseModel):
    """A resumable strategy/universe research matrix."""

    experiment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    strategy_names: list[str] = Field(min_length=1)
    universe: list[str] = Field(min_length=1)
    timeframe: str = "1d"
    mode: str = "event-driven"
    universe_snapshot_id: str = "CONFIGURED_UNIVERSE"
    benchmark_symbol: str | None = "NIFTY200"
    parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    cost_model: dict[str, Any] = Field(default_factory=dict)
    cost_model_version: str = "angel-nse-delivery-2026-04"
    max_workers: int = Field(default=1, ge=1, le=64)
    max_retries: int = Field(default=2, ge=0, le=5)
    stale_job_seconds: int = Field(default=3_600, ge=60, le=86_400)
    walk_forward_train_size: int = Field(default=252, ge=20)
    walk_forward_test_size: int = Field(default=63, ge=5)

    @field_validator("universe")
    @classmethod
    def normalize_universe(cls, value: list[str]) -> list[str]:
        symbols = [str(symbol).strip().upper() for symbol in value]
        if any(not symbol for symbol in symbols) or len(symbols) != len(set(symbols)):
            raise ValueError("Universe must contain unique non-empty symbols.")
        return symbols
