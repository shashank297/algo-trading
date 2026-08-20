from __future__ import annotations

import abc
from risk.models import RiskPolicy, TradeProposal


class RiskValidator(abc.ABC):
    @abc.abstractmethod
    def evaluate(self, proposal: TradeProposal, policy: RiskPolicy) -> tuple[float, list[str]]:
        """Return (approved_notional_cap, list_of_reasons).

        If no limit applies, return (proposal.requested_notional, []).
        If outright rejected, return (0.0, [reason]).
        """
        pass


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
        available_gross = max(gross_limit - proposal.current_gross_exposure, 0.0)

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
        available_sector = max(sector_limit - proposal.current_sector_exposure, 0.0)

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
        if proposal.daily_pnl <= -max_daily_loss:
            if proposal.risk_reducing_notional > 0:
                if proposal.risk_increasing_notional == 0:
                    return proposal.requested_notional, []
                return proposal.risk_reducing_notional, ["DAILY_LOSS_REDUCE_ONLY", "RISK_INCREASING_PORTION_REJECTED"]
            return 0.0, ["DAILY_LOSS_REDUCE_ONLY"]
        return proposal.requested_notional, []


class DrawdownValidator(RiskValidator):
    def evaluate(self, proposal: TradeProposal, policy: RiskPolicy) -> tuple[float, list[str]]:
        max_drawdown = policy.max_drawdown_pct
        if proposal.current_drawdown >= max_drawdown:
            if proposal.risk_reducing_notional > 0:
                if proposal.risk_increasing_notional == 0:
                    return proposal.requested_notional, []
                return proposal.risk_reducing_notional, ["DRAWDOWN_REDUCE_ONLY", "RISK_INCREASING_PORTION_REJECTED"]
            return 0.0, ["DRAWDOWN_REDUCE_ONLY"]
        return proposal.requested_notional, []


class MaxPositionsValidator(RiskValidator):
    def evaluate(self, proposal: TradeProposal, policy: RiskPolicy) -> tuple[float, list[str]]:
        if not proposal.is_pure_risk_reduction and proposal.open_position_count >= policy.max_open_positions and proposal.current_position_notional == 0:
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


