"""Regression tests for position sizing limits under top-ups, reversals, and breaches."""

from data_platform.contracts import OrderSide
from risk.models import RiskPolicy, TradeProposal
from risk.validators import PositionSizeValidator


def make_policy(max_position_pct: float = 0.05) -> RiskPolicy:
    return RiskPolicy(
        max_position_pct=max_position_pct,
        max_gross_exposure_pct=1.0,
        max_daily_loss_pct=0.01,
        max_drawdown_pct=0.05,
        max_sector_exposure_pct=0.20,
        max_open_positions=10,
        min_liquidity_crore=0.0,
        max_var_pct=0.05,
    )


def test_position_top_up_capped_at_remaining_limit():
    """Capital: 100k, Max pos: 5% (5k). Current long: 4k. Requested buy: 2k.
    Must approve at most 1k so resulting position <= 5k.
    """
    validator = PositionSizeValidator()
    policy = make_policy(max_position_pct=0.05)

    proposal = TradeProposal(
        symbol="RELIANCE",
        requested_notional=2000.0,
        capital=100000.0,
        current_position_notional=4000.0,
        order_side=OrderSide.BUY,
    )

    approved, reasons = validator.evaluate(proposal, policy)
    assert approved == 1000.0, f"Expected 1000.0, got {approved}"
    assert "notional_capped_by_risk_policy" in reasons


def test_position_short_top_up_capped():
    """Capital: 100k, Max pos: 5% (5k). Current short: -4k. Requested short: 2k (sell).
    Must approve at most 1k so resulting short <= 5k.
    """
    validator = PositionSizeValidator()
    policy = make_policy(max_position_pct=0.05)

    proposal = TradeProposal(
        symbol="RELIANCE",
        requested_notional=2000.0,
        capital=100000.0,
        current_position_notional=-4000.0,
        order_side=OrderSide.SELL,
    )

    approved, reasons = validator.evaluate(proposal, policy)
    assert approved == 1000.0, f"Expected 1000.0, got {approved}"
    assert "notional_capped_by_risk_policy" in reasons


def test_position_reversal_allowed_up_to_new_limit():
    """Capital: 100k, Max pos: 5% (5k). Current long: 4k. Requested sell: 6k (reversal to 2k short).
    Closing 4k is risk-reducing (fully allowed).
    New 2k short is <= 5k limit.
    Total approved should be 6000.0.
    """
    validator = PositionSizeValidator()
    policy = make_policy(max_position_pct=0.05)

    proposal = TradeProposal(
        symbol="RELIANCE",
        requested_notional=6000.0,
        capital=100000.0,
        current_position_notional=4000.0,
        order_side=OrderSide.SELL,
    )

    approved, reasons = validator.evaluate(proposal, policy)
    assert approved == 6000.0, f"Expected 6000.0, got {approved}"
    assert reasons == []


def test_position_reversal_capped_if_new_exposure_exceeds_limit():
    """Capital: 100k, Max pos: 5% (5k). Current long: 4k. Requested sell: 12k (would be 8k short).
    Closing 4k long: fully allowed (4k).
    New short portion: 8k, but capped at 5k.
    Total approved: 4k + 5k = 9k.
    """
    validator = PositionSizeValidator()
    policy = make_policy(max_position_pct=0.05)

    proposal = TradeProposal(
        symbol="RELIANCE",
        requested_notional=12000.0,
        capital=100000.0,
        current_position_notional=4000.0,
        order_side=OrderSide.SELL,
    )

    approved, reasons = validator.evaluate(proposal, policy)
    assert approved == 9000.0, f"Expected 9000.0, got {approved}"
    assert "notional_capped_by_risk_policy" in reasons


def test_existing_breach_rejects_further_increase():
    """Capital: 100k, Max pos: 5% (5k). Current long: 6k (already breached). Requested buy: 1k.
    Must approve 0.0.
    """
    validator = PositionSizeValidator()
    policy = make_policy(max_position_pct=0.05)

    proposal = TradeProposal(
        symbol="RELIANCE",
        requested_notional=1000.0,
        capital=100000.0,
        current_position_notional=6000.0,
        order_side=OrderSide.BUY,
    )

    approved, reasons = validator.evaluate(proposal, policy)
    assert approved == 0.0, f"Expected 0.0, got {approved}"
    assert "notional_capped_by_risk_policy" in reasons or "position_limit_reached" in reasons


def test_existing_breach_allows_reduce_only():
    """Capital: 100k, Max pos: 5% (5k). Current long: 6k. Requested sell: 2k (pure risk reduction).
    Must approve 2000.0 in full.
    """
    validator = PositionSizeValidator()
    policy = make_policy(max_position_pct=0.05)

    proposal = TradeProposal(
        symbol="RELIANCE",
        requested_notional=2000.0,
        capital=100000.0,
        current_position_notional=6000.0,
        order_side=OrderSide.SELL,
    )

    approved, reasons = validator.evaluate(proposal, policy)
    assert approved == 2000.0, f"Expected 2000.0, got {approved}"
    assert reasons == []
