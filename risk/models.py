"""Validated risk inputs and machine-readable decisions."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum

import math
from pydantic import BaseModel, Field, field_validator

from data_platform.contracts import OrderSide


class RiskAction(str, Enum):
    PASS = "PASS"
    MODIFY = "MODIFY"
    REJECT = "REJECT"


class RiskPolicy(BaseModel):
    """Conservative limits used unless the operator explicitly changes config."""

    max_position_pct: float = Field(default=0.05, gt=0, le=1)
    max_gross_exposure_pct: float = Field(default=0.20, gt=0, le=1)
    max_sector_exposure_pct: float = Field(default=0.20, gt=0, le=1)
    max_daily_loss_pct: float = Field(default=0.01, gt=0, le=1)
    max_drawdown_pct: float = Field(default=0.05, gt=0, le=1)
    # New production-grade limits
    max_open_positions: int = Field(default=20, ge=1, le=500)
    max_var_pct: float = Field(default=0.02, gt=0, le=1)  # Max 2% daily portfolio VaR at 95%
    min_liquidity_crore: float = Field(default=10.0, ge=0)  # Skip stocks < ₹10 Cr daily turnover


class TradeProposal(BaseModel):
    """Context required for a deterministic paper-trade risk decision."""

    symbol: str
    sector: str = "Unknown"
    requested_notional: float = Field(gt=0)
    capital: float = Field(gt=0)
    current_position_notional: float = 0.0  # Signed: >0 long, <0 short
    order_side: OrderSide = OrderSide.BUY
    current_gross_exposure: float = Field(default=0, ge=0)
    current_sector_exposure: float = Field(default=0, ge=0)
    daily_pnl: float = 0.0
    current_drawdown: float = Field(default=0, ge=0)
    stop_loss_pct: float | None = None
    open_position_count: int = 0
    daily_turnover_crore: float | None = None
    estimated_portfolio_var_pct: float | None = None

    @field_validator("requested_notional", "capital", "current_position_notional", "current_gross_exposure", "current_sector_exposure", "daily_pnl", "current_drawdown")
    @classmethod
    def validate_finite_floats(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError(f"Float value must be finite, got {value}")
        return float(value)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("A risk proposal requires a symbol.")
        return normalized

    @property
    def signed_order_notional(self) -> float:
        """Return signed requested notional (+ for BUY, - for SELL)."""
        return self.requested_notional if self.order_side == OrderSide.BUY else -self.requested_notional

    @property
    def resulting_position_notional(self) -> float:
        """Return projected signed position notional after execution."""
        return self.current_position_notional + self.signed_order_notional

    @property
    def risk_reducing_notional(self) -> float:
        """Return the portion of requested notional that reduces existing exposure toward flat."""
        if (self.current_position_notional > 0 and self.order_side == OrderSide.SELL) or (
            self.current_position_notional < 0 and self.order_side == OrderSide.BUY
        ):
            return min(self.requested_notional, abs(self.current_position_notional))
        return 0.0

    @property
    def risk_increasing_notional(self) -> float:
        """Return the portion of requested notional that expands or initiates new risk."""
        return max(self.requested_notional - self.risk_reducing_notional, 0.0)

    @property
    def is_pure_risk_reduction(self) -> bool:
        """True if the entire order exclusively liquidates or reduces an existing position with zero new risk."""
        return self.risk_reducing_notional > 0 and self.risk_increasing_notional == 0

    @property
    def is_reversal(self) -> bool:
        """True if the order crosses through zero, closing an existing position and opening new opposing exposure."""
        return self.risk_reducing_notional > 0 and self.risk_increasing_notional > 0

    @property
    def net_exposure_reducing(self) -> bool:
        """True if final absolute position exposure is strictly less than initial absolute exposure."""
        if self.current_position_notional == 0:
            return False
        return abs(self.resulting_position_notional) < abs(self.current_position_notional)

    @property
    def is_risk_reducing(self) -> bool:
        """Safety alias: true only if net exposure decreases."""
        return self.net_exposure_reducing



class RiskDecision(BaseModel):
    """An independent pass, sizing modification, or rejection."""

    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    action: RiskAction
    requested_notional: float
    approved_notional: float
    reasons: list[str]
    policy: RiskPolicy
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def storage_payload(self, run_id: str | None = None, experiment_id: str | None = None) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "run_id": run_id,
            "experiment_id": experiment_id,
            "symbol": self.symbol,
            "decision": self.action.value,
            "requested_notional": self.requested_notional,
            "approved_notional": self.approved_notional,
            "reasons_json": json.dumps(self.reasons),
            "policy_json": self.policy.model_dump_json(),
            "decided_at": self.decided_at,
        }
