"""Immutable research-family and trial evidence models."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ResearchIntegrityError(RuntimeError):
    """Base error for a failure that must stop governed research."""


class ResearchLineageError(ResearchIntegrityError):
    """Raised when authoritative dataset or frame lineage is unavailable."""


class ResearchCertificationError(ResearchIntegrityError):
    """Raised when required research certification evidence is invalid."""


class ResearchCausalityError(ResearchIntegrityError):
    """Raised when research causality evidence is invalid."""


def is_research_governance_error(error: BaseException) -> bool:
    """Return whether an error must abort a governed candidate search.

    Candidate-local strategy failures deliberately remain outside this list.
    """

    from trading_stack.pipeline import DataQualityError as PipelineDataQualityError
    from validators.data_quality import DataQualityError as ValidatorDataQualityError

    return isinstance(
        error,
        (
            ResearchIntegrityError,
            PipelineDataQualityError,
            ValidatorDataQualityError,
        ),
    )


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class TrialStatus(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INVALIDATED = "INVALIDATED"
    CANCELLED = "CANCELLED"


class ExperimentFamilySpec(BaseModel):
    experiment_family_id: str
    hypothesis: str = Field(min_length=1)
    strategy_names: list[str] = Field(min_length=1)
    strategy_versions: list[str] = Field(min_length=1)
    universe_snapshot_id: str
    timeframe: str
    feature_versions: list[str] = Field(min_length=1)
    cost_model_version: str
    parameter_space: dict[str, Any]
    maximum_trials: int = Field(gt=0)
    selection_metric: str
    walk_forward_design: dict[str, Any]
    regime_conditions: dict[str, Any] = Field(default_factory=dict)
    asset_cluster_conditions: dict[str, Any] = Field(default_factory=dict)
    source_revision: str
    operator_notes: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def definition_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json", exclude={"created_at", "operator_notes"}))


class ResearchTrial(BaseModel):
    experiment_family_id: str
    strategy_name: str
    strategy_version: str
    scope: str
    timeframe: str
    parameters: dict[str, Any]
    source_revision: str
    data_hash: str
    cost_model_hash: str
    symbol: str | None = None
    universe_snapshot_id: str | None = None
    feature_version: str | None = None
    cost_model_version: str | None = None
    frame_certification_id: str | None = None
    fold_id: str | None = None
    train_start: datetime | None = None
    train_end: datetime | None = None
    test_start: datetime | None = None
    test_end: datetime | None = None
    parent_trial_id: str | None = None
    status: TrialStatus = TrialStatus.PLANNED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def parameter_hash(self) -> str:
        return canonical_hash(self.parameters)

    @property
    def trial_id(self) -> str:
        return canonical_hash(self.model_dump(mode="json", exclude={"status", "created_at"}))
