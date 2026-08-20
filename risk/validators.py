from __future__ import annotations

import abc
import math
from typing import Any
from risk.models import RiskPolicy, TradeProposal


class RiskValidator(abc.ABC):
    @abc.abstractmethod
    def evaluate(self, proposal: TradeProposal, policy: RiskPolicy) -> tuple[float, list[str]]:
        """Return (approved_notional_cap, list_of_reasons).

        If no limit applies, return (proposal.requested_notional, []).
        If outright rejected, return (0.0, [reason]).
        """
        pass


class RequiredRiskStateValidator(RiskValidator):
    """Fail-closed check that mandatory risk state is provided and finite for risk-increasing orders."""

    def evaluate(self, proposal: TradeProposal, policy: RiskPolicy) -> tuple[float, list[str]]:
        if proposal.is_pure_risk_reduction:
            return proposal.requested_notional, []

        reasons: list[str] = []

        def check_field(name: str, val: Any, allow_negative: bool = False, require_positive: bool = False, is_int: bool = False) -> None:
            if val is None:
                reasons.append(f"MISSING_RISK_STATE:{name}")
                return
            if is_int:
                if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                    reasons.append(f"INVALID_RISK_STATE:{name}")
                return
            if not isinstance(val, (int, float)) or isinstance(val, bool) or not math.isfinite(val):
                reasons.append(f"INVALID_RISK_STATE:{name}")
                return
            if require_positive and val <= 0:
                reasons.append(f"INVALID_RISK_STATE:{name}")
                return
            if not allow_negative and val < 0:
                reasons.append(f"INVALID_RISK_STATE:{name}")
                return

        check_field("capital", proposal.capital, require_positive=True)
        check_field("requested_notional", proposal.requested_notional, require_positive=True)
        check_field("current_position_notional", proposal.current_position_notional, allow_negative=True)
        check_field("daily_pnl", proposal.daily_pnl, allow_negative=True)
        check_field("current_gross_exposure", proposal.current_gross_exposure)
        check_field("current_sector_exposure", proposal.current_sector_exposure)
        check_field("current_drawdown", proposal.current_drawdown)
        check_field("daily_turnover_crore", proposal.daily_turnover_crore)
        check_field("estimated_portfolio_var_pct", proposal.estimated_portfolio_var_pct)
        check_field("open_position_count", proposal.open_position_count, is_int=True)

        if reasons:
            return 0.0, reasons

        return proposal.requested_notional, []


class PositionSizeValidator(RiskValidator):
    def evaluate(self, proposal: TradeProposal, policy: RiskPolicy) -> tuple[float, list[str]]:
        if proposal.is_pure_risk_reduction:
            return proposal.requested_notional, []
        position_limit = proposal.capital * policy.max_position_pct
        projected_abs_position = abs(proposal.resulting_position_notional)
        if projected_abs_position > position_limit:
            # Allow the risk-reducing portion plus allowable new exposure
            base_offset = abs(proposal.current_position_notional) if proposal.net_exposure_reducing else 0.0
            available_increasing = max(position_limit - base_offset, 0.0)
            capped_notional = proposal.risk_reducing_notional + available_increasing
            if capped_notional < proposal.requested_notional:
                return capped_notional, ["position_limit_reached" if position_limit <= 0 else "notional_capped_by_risk_policy"]
        return proposal.requested_notional, []


class PortfolioExposureValidator(RiskValidator):
    def evaluate(self, proposal: TradeProposal, policy: RiskPolicy) -> tuple[float, list[str]]:
        if proposal.is_pure_risk_reduction:
            return proposal.requested_notional, []
        gross_limit = proposal.capital * policy.max_gross_exposure_pct
        current_gross = proposal.current_gross_exposure if proposal.current_gross_exposure is not None else 0.0
        available_gross = max(gross_limit - current_gross, 0.0)

        if available_gross <= 0:
            if proposal.risk_reducing_notional > 0:
                return proposal.risk_reducing_notional, ["gross_exposure_limit_reached", "RISK_INCREASING_PORTION_REJECTED"]
            return 0.0, ["gross_exposure_limit_reached"]
        elif proposal.risk_increasing_notional > available_gross:
            capped_notional = proposal.risk_reducing_notional + available_gross
            return capped_notional, ["notional_capped_by_risk_policy"]
        return proposal.requested_notional, []


class SectorExposureValidator(RiskValidator):
    def evaluate(self, proposal: TradeProposal, policy: RiskPolicy) -> tuple[float, list[str]]:
        if proposal.is_pure_risk_reduction:
            return proposal.requested_notional, []
        sector_limit = proposal.capital * policy.max_sector_exposure_pct
        current_sector = proposal.current_sector_exposure if proposal.current_sector_exposure is not None else 0.0
        available_sector = max(sector_limit - current_sector, 0.0)

        if available_sector <= 0:
            if proposal.risk_reducing_notional > 0:
                return proposal.risk_reducing_notional, ["sector_exposure_limit_reached", "RISK_INCREASING_PORTION_REJECTED"]
            return 0.0, ["sector_exposure_limit_reached"]
        elif proposal.risk_increasing_notional > available_sector:
            capped_notional = proposal.risk_reducing_notional + available_sector
            return capped_notional, ["notional_capped_by_risk_policy"]
        return proposal.requested_notional, []


class DailyLossValidator(RiskValidator):
    def evaluate(self, proposal: TradeProposal, policy: RiskPolicy) -> tuple[float, list[str]]:
        max_daily_loss = proposal.capital * policy.max_daily_loss_pct
        daily_pnl = proposal.daily_pnl if proposal.daily_pnl is not None else 0.0
        if daily_pnl <= -max_daily_loss:
            if proposal.risk_reducing_notional > 0:
                if proposal.risk_increasing_notional == 0:
                    return proposal.requested_notional, []
                return proposal.risk_reducing_notional, ["DAILY_LOSS_REDUCE_ONLY", "RISK_INCREASING_PORTION_REJECTED"]
            return 0.0, ["DAILY_LOSS_REDUCE_ONLY"]
        return proposal.requested_notional, []


class DrawdownValidator(RiskValidator):
    def evaluate(self, proposal: TradeProposal, policy: RiskPolicy) -> tuple[float, list[str]]:
        max_drawdown = policy.max_drawdown_pct
        current_drawdown = proposal.current_drawdown if proposal.current_drawdown is not None else 0.0
        if current_drawdown >= max_drawdown:
            if proposal.risk_reducing_notional > 0:
                if proposal.risk_increasing_notional == 0:
                    return proposal.requested_notional, []
                return proposal.risk_reducing_notional, ["DRAWDOWN_REDUCE_ONLY", "RISK_INCREASING_PORTION_REJECTED"]
            return 0.0, ["DRAWDOWN_REDUCE_ONLY"]
        return proposal.requested_notional, []


class MaxPositionsValidator(RiskValidator):
    def evaluate(self, proposal: TradeProposal, policy: RiskPolicy) -> tuple[float, list[str]]:
        open_count = proposal.open_position_count if proposal.open_position_count is not None else 0
        if not proposal.is_pure_risk_reduction and open_count >= policy.max_open_positions and proposal.current_position_notional == 0:
            return 0.0, ["max_open_positions_limit_reached"]
        return proposal.requested_notional, []


class TurnoverLiquidityValidator(RiskValidator):
    def evaluate(self, proposal: TradeProposal, policy: RiskPolicy) -> tuple[float, list[str]]:
        if proposal.is_pure_risk_reduction:
            return proposal.requested_notional, []
        if proposal.daily_turnover_crore is not None and proposal.daily_turnover_crore < policy.min_liquidity_crore:
            if proposal.risk_reducing_notional > 0:
                return proposal.risk_reducing_notional, ["insufficient_daily_liquidity", "RISK_INCREASING_PORTION_REJECTED"]
            return 0.0, ["insufficient_daily_liquidity"]
        return proposal.requested_notional, []


class VaRValidator(RiskValidator):
    def evaluate(self, proposal: TradeProposal, policy: RiskPolicy) -> tuple[float, list[str]]:
        if proposal.is_pure_risk_reduction:
            return proposal.requested_notional, []
        if proposal.estimated_portfolio_var_pct is not None and proposal.estimated_portfolio_var_pct > policy.max_var_pct:
            if proposal.risk_reducing_notional > 0:
                return proposal.risk_reducing_notional, ["var_limit_exceeded", "RISK_INCREASING_PORTION_REJECTED"]
            return 0.0, ["var_limit_exceeded"]
        return proposal.requested_notional, []


