"""Rule-based risk gate kept separate from strategy and agent reasoning."""

from __future__ import annotations

from risk.models import RiskAction, RiskDecision, RiskPolicy, TradeProposal
from risk.validators import (
    DailyLossValidator,
    DrawdownValidator,
    MaxPositionsValidator,
    PortfolioExposureValidator,
    PositionSizeValidator,
    RiskValidator,
    SectorExposureValidator,
    TurnoverLiquidityValidator,
)


class RiskEngine:
    """Apply conservative portfolio and loss limits to one proposed trade."""

    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or RiskPolicy()
        self.validators: list[RiskValidator] = [
            DailyLossValidator(),
            DrawdownValidator(),
            SectorExposureValidator(),
            PortfolioExposureValidator(),
            PositionSizeValidator(),
            MaxPositionsValidator(),
            TurnoverLiquidityValidator(),
        ]


    def evaluate(self, proposal: TradeProposal) -> RiskDecision:
        """Return a deterministic decision based on modular validators."""

        reasons = []
        approved_notional = proposal.requested_notional
        
        for validator in self.validators:
            cap, validator_reasons = validator.evaluate(proposal, self.policy)
            if cap < approved_notional:
                approved_notional = cap
            reasons.extend(validator_reasons)
            
        # Deduplicate reasons while preserving order
        unique_reasons = []
        for reason in reasons:
            if reason not in unique_reasons:
                unique_reasons.append(reason)
        reasons = unique_reasons

        monetary_tolerance = max(proposal.capital * 1e-12, 1e-9)

        if approved_notional <= 0:
            return RiskDecision(
                symbol=proposal.symbol,
                action=RiskAction.REJECT,
                requested_notional=proposal.requested_notional,
                approved_notional=0.0,
                reasons=reasons,
                policy=self.policy,
            )
        elif approved_notional + monetary_tolerance < proposal.requested_notional:
            return RiskDecision(
                symbol=proposal.symbol,
                action=RiskAction.MODIFY,
                requested_notional=proposal.requested_notional,
                approved_notional=approved_notional,
                reasons=reasons,
                policy=self.policy,
            )
        
        return RiskDecision(
            symbol=proposal.symbol,
            action=RiskAction.PASS,
            requested_notional=proposal.requested_notional,
            approved_notional=proposal.requested_notional,
            reasons=["within_conservative_limits"],
            policy=self.policy,
        )
