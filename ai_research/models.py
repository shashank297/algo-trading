"""Schemas that force agent responses to distinguish evidence from reasoning."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class ClaimKind(str, Enum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    ASSUMPTION = "ASSUMPTION"
    UNCERTAINTY = "UNCERTAINTY"


class Claim(BaseModel):
    """One attributable statement in an agent report."""

    kind: ClaimKind
    statement: str = Field(min_length=1, max_length=2000)
    data_sources: list[str] = Field(default_factory=list)


class AgentOutput(BaseModel):
    """A validated agent result that cannot contain unclassified assertions."""

    agent: str
    asset: str
    signal: str = "HOLD"
    confidence: float = Field(ge=0, le=1)
    claims: list[Claim] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("agent", "asset", "signal")
    @classmethod
    def normalize_identifiers(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("Agent output identifiers must not be empty.")
        return normalized


class ResearchGoal(BaseModel):
    """A bounded request that may create experiments but cannot place live orders."""

    goal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    timeframe: str
    strategy_name: str = "trend_following"
    parameters: dict[str, object] = Field(default_factory=dict)
    max_cost_usd: float = Field(default=1.0, gt=0)
    max_tokens: int = Field(default=20_000, ge=1_000, le=1_000_000)
    paper_approved: bool = False
    paper_session_id: str | None = None

    @field_validator("symbol", "timeframe", "strategy_name")
    @classmethod
    def normalize_goal_values(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("Research goal values must not be empty.")
        return normalized
