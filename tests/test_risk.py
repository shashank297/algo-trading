import math
import pandas as pd
import pytest

from data_platform.contracts import OrderSide
from risk.engine import RiskEngine
from risk.factory import build_risk_engine, build_risk_policy
from risk.models import RiskAction, RiskPolicy, TradeProposal



def make_proposal(**kwargs) -> TradeProposal:
    defaults = {
        "symbol": "RELIANCE",
        "requested_notional": 1000.0,
        "capital": 100000.0,
        "current_gross_exposure": 0.0,
        "current_sector_exposure": 0.0,
        "daily_pnl": 0.0,
        "current_drawdown": 0.0,
        "open_position_count": 0,
        "daily_turnover_crore": 15.0,
        "estimated_portfolio_var_pct": 0.01,
        "order_side": OrderSide.BUY,
    }
    defaults.update(kwargs)
    return TradeProposal(**defaults)


def test_authoritative_risk_factory_uses_research_config_and_rejects_missing_section():
    config = {"research": {"risk": {
        "max_position_pct": 0.05,
        "max_gross_exposure_pct": 0.20,
        "max_daily_loss_pct": 0.03,
        "max_drawdown_pct": 0.15,
        "max_sector_exposure_pct": 0.40,
        "max_open_positions": 20,
        "max_var_pct": 0.02,
        "min_liquidity_crore": 0.0,
    }}}
    policy = build_risk_policy(config)
    engine = build_risk_engine(config)
    assert policy.max_position_pct == 0.05
    assert engine.policy.model_dump() == policy.model_dump()
    with pytest.raises(ValueError, match="research.risk"):
        build_risk_engine({"research": {}})


@pytest.mark.parametrize("missing", [
    "max_position_pct", "max_gross_exposure_pct", "max_daily_loss_pct",
    "max_drawdown_pct", "max_sector_exposure_pct", "max_open_positions",
    "max_var_pct", "min_liquidity_crore",
])
def test_authoritative_risk_factory_rejects_missing_material_fields(missing):
    config = {"research": {"risk": {
        "max_position_pct": 0.05, "max_gross_exposure_pct": 0.20,
        "max_daily_loss_pct": 0.03, "max_drawdown_pct": 0.15,
        "max_sector_exposure_pct": 0.40, "max_open_positions": 20,
        "max_var_pct": 0.02, "min_liquidity_crore": 0.0,
    }}}
    del config["research"]["risk"][missing]
    with pytest.raises(ValueError, match=missing):
        build_risk_policy(config)


def test_authoritative_risk_factory_rejects_unknown_fields():
    config = {"research": {"risk": {
        "max_position_pct": 0.05, "max_gross_exposure_pct": 0.20,
        "max_daily_loss_pct": 0.03, "max_drawdown_pct": 0.15,
        "max_sector_exposure_pct": 0.40, "max_open_positions": 20,
        "max_var_pct": 0.02, "min_liquidity_crore": 0.0,
        "max_var_pcts": 0.02,
    }}}
    with pytest.raises(ValueError, match="unknown fields"):
        build_risk_policy(config)


def test_baseline_engine_interception():
    engine = RiskEngine()
    proposal = make_proposal(
        symbol="RELIANCE",
        requested_notional=1000.0,
        capital=100000.0,
        order_side=OrderSide.BUY,
    )
    decision = engine.evaluate(proposal)
    assert decision.action == RiskAction.PASS
    assert decision.approved_notional == 1000.0
    assert "within_conservative_limits" in decision.reasons


def test_position_limit_rejected():
    policy = RiskPolicy(max_position_pct=0.05)
    engine = RiskEngine(policy=policy)
    # Requested notional is 6000, max position limit is 5% of 100000 = 5000.
    proposal = make_proposal(
        symbol="RELIANCE",
        requested_notional=6000.0,
        capital=100000.0,
        order_side=OrderSide.BUY,
    )
    decision = engine.evaluate(proposal)
    assert decision.action == RiskAction.MODIFY
    assert decision.approved_notional == 5000.0
    assert "notional_capped_by_risk_policy" in decision.reasons


def test_portfolio_limit_rejected():
    policy = RiskPolicy(max_gross_exposure_pct=0.20)
    engine = RiskEngine(policy=policy)
    # Portfolio already has 18k exposure, we want 3k more -> total 21k
    # Max gross is 20k (20% of 100k). Available gross is 2k.
    proposal = make_proposal(
        symbol="RELIANCE",
        requested_notional=3000.0,
        capital=100000.0,
        current_gross_exposure=18000.0,
        order_side=OrderSide.BUY,
    )
    decision = engine.evaluate(proposal)
    assert decision.action == RiskAction.MODIFY
    assert decision.approved_notional == 2000.0
    assert "notional_capped_by_risk_policy" in decision.reasons


def test_drawdown_limit_rejected_for_new_risk():
    policy = RiskPolicy(max_drawdown_pct=0.10)
    engine = RiskEngine(policy=policy)
    proposal = make_proposal(
        symbol="RELIANCE",
        requested_notional=1000.0,
        capital=100000.0,
        current_drawdown=0.15,  # Drawdown is 15%, limit is 10%
        order_side=OrderSide.BUY,
    )
    decision = engine.evaluate(proposal)
    assert decision.action == RiskAction.REJECT
    assert "DRAWDOWN_REDUCE_ONLY" in decision.reasons


def test_emergency_liquidation_allowed_under_daily_loss_breach():
    """Emergency liquidation of existing long position is permitted even when daily loss is breached."""
    policy = RiskPolicy(max_daily_loss_pct=0.01)  # 1% daily loss = 1,000 on 100k
    engine = RiskEngine(policy=policy)
    # Portfolio is down 1,500 (> 1,000 daily loss limit), closing 10,000 long position
    proposal = TradeProposal(
        symbol="RELIANCE",
        requested_notional=10000.0,
        capital=100000.0,
        current_position_notional=10000.0,  # Long 10k
        order_side=OrderSide.SELL,  # Selling to liquidate
        daily_pnl=-1500.0,
    )
    assert proposal.is_pure_risk_reduction is True
    decision = engine.evaluate(proposal)
    assert decision.action == RiskAction.PASS
    assert decision.approved_notional == 10000.0


def test_emergency_liquidation_allowed_under_drawdown_breach():
    """Emergency liquidation of existing short position is permitted even when drawdown is breached."""
    policy = RiskPolicy(max_drawdown_pct=0.05)  # 5% drawdown limit
    engine = RiskEngine(policy=policy)
    # Portfolio is at 10% drawdown, buying to cover 10,000 short position
    proposal = TradeProposal(
        symbol="RELIANCE",
        requested_notional=10000.0,
        capital=100000.0,
        current_position_notional=-10000.0,  # Short 10k
        order_side=OrderSide.BUY,  # Buying to cover
        current_drawdown=0.10,
    )
    assert proposal.is_pure_risk_reduction is True
    decision = engine.evaluate(proposal)
    assert decision.action == RiskAction.PASS
    assert decision.approved_notional == 10000.0


def test_reversal_order_split_under_daily_loss_breach():
    """Oversized reversal order (Long +100k + SELL 150k) allows 100k liquidation while rejecting 50k new short."""
    policy = RiskPolicy(max_daily_loss_pct=0.01)
    engine = RiskEngine(policy=policy)
    proposal = make_proposal(
        symbol="TATASTEEL",
        requested_notional=150000.0,
        capital=1000000.0,
        current_position_notional=100000.0,  # Long 100k
        order_side=OrderSide.SELL,  # Reversal: SELL 150k
        daily_pnl=-15000.0,  # Breaching 10k daily loss limit
        current_gross_exposure=100000.0,
    )
    assert proposal.is_reversal is True
    assert proposal.risk_reducing_notional == 100000.0
    assert proposal.risk_increasing_notional == 50000.0
    assert proposal.is_pure_risk_reduction is False

    decision = engine.evaluate(proposal)
    assert decision.action == RiskAction.MODIFY
    assert decision.approved_notional == 100000.0  # Exactly the 100k liquidation portion
    assert "DAILY_LOSS_REDUCE_ONLY" in decision.reasons
    assert "RISK_INCREASING_PORTION_REJECTED" in decision.reasons


def test_complete_10_case_exposure_matrix():
    """Comprehensive test across all 10 combinations of current position, order side, and notional sizes."""
    # 1. Long +100k + SELL 40k -> reducing (40k reduce, 0 new)
    p1 = TradeProposal(symbol="S1", requested_notional=40000.0, capital=1000000.0, current_position_notional=100000.0, order_side=OrderSide.SELL)
    assert p1.risk_reducing_notional == 40000.0
    assert p1.risk_increasing_notional == 0.0
    assert p1.is_pure_risk_reduction is True

    # 2. Long +100k + SELL 100k -> reducing / flat (100k reduce, 0 new)
    p2 = TradeProposal(symbol="S2", requested_notional=100000.0, capital=1000000.0, current_position_notional=100000.0, order_side=OrderSide.SELL)
    assert p2.risk_reducing_notional == 100000.0
    assert p2.risk_increasing_notional == 0.0
    assert p2.is_pure_risk_reduction is True

    # 3. Long +100k + SELL 150k -> reversal (100k reduce, 50k new)
    p3 = TradeProposal(symbol="S3", requested_notional=150000.0, capital=1000000.0, current_position_notional=100000.0, order_side=OrderSide.SELL)
    assert p3.risk_reducing_notional == 100000.0
    assert p3.risk_increasing_notional == 50000.0
    assert p3.is_reversal is True
    assert p3.is_pure_risk_reduction is False

    # 4. Long +100k + BUY 10k -> increasing (0 reduce, 10k new)
    p4 = TradeProposal(symbol="S4", requested_notional=10000.0, capital=1000000.0, current_position_notional=100000.0, order_side=OrderSide.BUY)
    assert p4.risk_reducing_notional == 0.0
    assert p4.risk_increasing_notional == 10000.0
    assert p4.is_pure_risk_reduction is False

    # 5. Short -100k + BUY 40k -> reducing (40k reduce, 0 new)
    p5 = TradeProposal(symbol="S5", requested_notional=40000.0, capital=1000000.0, current_position_notional=-100000.0, order_side=OrderSide.BUY)
    assert p5.risk_reducing_notional == 40000.0
    assert p5.risk_increasing_notional == 0.0
    assert p5.is_pure_risk_reduction is True

    # 6. Short -100k + BUY 100k -> reducing / flat (100k reduce, 0 new)
    p6 = TradeProposal(symbol="S6", requested_notional=100000.0, capital=1000000.0, current_position_notional=-100000.0, order_side=OrderSide.BUY)
    assert p6.risk_reducing_notional == 100000.0
    assert p6.risk_increasing_notional == 0.0
    assert p6.is_pure_risk_reduction is True

    # 7. Short -100k + BUY 150k -> reversal (100k reduce, 50k new)
    p7 = TradeProposal(symbol="S7", requested_notional=150000.0, capital=1000000.0, current_position_notional=-100000.0, order_side=OrderSide.BUY)
    assert p7.risk_reducing_notional == 100000.0
    assert p7.risk_increasing_notional == 50000.0
    assert p7.is_reversal is True

    # 8. Short -100k + SELL 10k -> increasing (0 reduce, 10k new)
    p8 = TradeProposal(symbol="S8", requested_notional=10000.0, capital=1000000.0, current_position_notional=-100000.0, order_side=OrderSide.SELL)
    assert p8.risk_reducing_notional == 0.0
    assert p8.risk_increasing_notional == 10000.0

    # 9. Flat 0 + BUY 10k -> increasing (0 reduce, 10k new)
    p9 = TradeProposal(symbol="S9", requested_notional=10000.0, capital=1000000.0, current_position_notional=0.0, order_side=OrderSide.BUY)
    assert p9.risk_reducing_notional == 0.0
    assert p9.risk_increasing_notional == 10000.0

    # 10. Flat 0 + SELL 10k -> increasing (0 reduce, 10k new)
    p10 = TradeProposal(symbol="S10", requested_notional=10000.0, capital=1000000.0, current_position_notional=0.0, order_side=OrderSide.SELL)
    assert p10.risk_reducing_notional == 0.0
    assert p10.risk_increasing_notional == 10000.0


def test_malformed_financial_state_rejected():
    """NaN, Inf, or negative financial inputs fail validation immediately."""
    with pytest.raises(ValueError):
        TradeProposal(symbol="INFCO", requested_notional=float("inf"), capital=100000.0)

    with pytest.raises(ValueError):
        TradeProposal(symbol="NANCO", requested_notional=float("nan"), capital=100000.0)

    with pytest.raises(ValueError):
        TradeProposal(symbol="NEGCO", requested_notional=-100.0, capital=100000.0)

    with pytest.raises(ValueError):
        TradeProposal(symbol="CAPCO", requested_notional=100.0, capital=-100000.0)


def test_max_open_positions_limit():
    policy = RiskPolicy(max_open_positions=10)
    engine = RiskEngine(policy=policy)
    proposal = make_proposal(
        symbol="INFY",
        requested_notional=1000.0,
        capital=100000.0,
        open_position_count=10,
    )
    decision = engine.evaluate(proposal)
    assert decision.action == RiskAction.REJECT
    assert "max_open_positions_limit_reached" in decision.reasons


def test_min_liquidity_crore_limit():
    policy = RiskPolicy(min_liquidity_crore=10.0)
    engine = RiskEngine(policy=policy)
    # Stock has only ₹2 Cr daily turnover
    proposal = make_proposal(
        symbol="PENNYSTOCK",
        requested_notional=1000.0,
        capital=100000.0,
        daily_turnover_crore=2.0,
    )
    decision = engine.evaluate(proposal)
    assert decision.action == RiskAction.REJECT
    assert "insufficient_daily_liquidity" in decision.reasons


def test_end_to_end_oversized_reversal_position_flattening():
    """End-to-end trace: Long +100 shares (@1,000) proposing SELL 150 under daily loss breach results in exactly 0 shares."""
    from trading_stack.backtest import ExecutionModel, PaperBroker

    policy = RiskPolicy(max_daily_loss_pct=0.01)  # 1% limit
    engine = RiskEngine(policy=policy)
    starting_capital = 1_000_000.0
    price = 1000.0
    current_qty = 100.0  # +₹100,000 long position
    current_notional = current_qty * price

    # Strategy wants to flip short to -50 shares -> delta = -150 shares (₹150,000 requested)
    requested_delta = -150.0
    requested_notional = abs(requested_delta) * price
    side = OrderSide.SELL

    proposal = make_proposal(
        symbol="RELIANCE",
        requested_notional=requested_notional,
        capital=starting_capital,
        current_position_notional=current_notional,
        order_side=side,
        daily_pnl=-15000.0,  # Daily loss limit breached
        current_gross_exposure=current_notional,
    )
    decision = engine.evaluate(proposal)
    assert decision.action == RiskAction.MODIFY
    assert decision.approved_notional == 100000.0

    # Downstream order sizing
    approved_shares = math.floor(min(decision.approved_notional, requested_notional) / price)
    approved_delta_qty = approved_shares if side == OrderSide.BUY else -approved_shares
    desired_qty = current_qty + approved_delta_qty
    order_qty = abs(desired_qty - current_qty)

    # Invariant: executed notional <= approved notional
    assert order_qty * price <= decision.approved_notional
    assert order_qty == 100.0

    # Broker execution
    broker = PaperBroker(ExecutionModel())
    result = broker.execute_order(
        run_id="reversal-test",
        symbol="RELIANCE",
        side=side,
        quantity=order_qty,
        price=price,
        timestamp=pd.Timestamp("2026-08-17 10:00:00+05:30").to_pydatetime(),
        risk_decision=decision,
    )
    assert result["order"]["status"] == "FILLED"
    assert result["fill"]["quantity"] == 100.0

    # Final position state
    final_qty = current_qty - result["fill"]["quantity"]
    assert final_qty == 0.0  # Position is flattened to flat 0, NOT -50 short!


def test_rejected_execution_zero_accounting_mutation():
    """Rejected execution must cause zero cash, position, fee, or fill mutation."""
    from trading_stack.backtest import ExecutionModel, PaperBroker

    # Cost model with 500 bps ceiling; order will experience 600 bps drag
    exec_model = ExecutionModel(indian_delivery_costs={"spread_bps": 300.0, "slippage_bps": 300.0, "max_allowed_drag_bps": 500.0})
    broker = PaperBroker(exec_model)


    start_cash = 500_000.0
    start_qty = 50.0


    result = broker.execute_order(
        run_id="reject-test",
        symbol="TEST",
        side=OrderSide.BUY,
        quantity=10.0,
        price=100.0,
        timestamp=pd.Timestamp("2026-08-17 10:00:00+05:30").to_pydatetime(),
        volume=1000.0,
    )
    # Order rejected due to drag > 500 bps
    assert result["order"]["status"] == "REJECTED"
    assert result["fill"] is None
    assert result["cost_components"] is None

    # Verify accounting invariances
    cash_delta = 0.0 if result["fill"] is None else result["fill"]["quantity"] * result["fill"]["price"]
    qty_delta = 0.0 if result["fill"] is None else result["fill"]["quantity"]
    fees = result["order"]["fees"]

    end_cash = start_cash - cash_delta - fees
    end_qty = start_qty + qty_delta

    assert end_cash == start_cash
    assert end_qty == start_qty
    assert fees == 0.0


def test_turnover_liquidity_validator_allows_pure_reduction():
    """Illiquid stock must be allowed to liquidate if order is pure risk reduction."""
    from risk.validators import TurnoverLiquidityValidator

    validator = TurnoverLiquidityValidator()
    policy = RiskPolicy(min_liquidity_crore=5.0)

    # 1. New BUY order in illiquid stock (turnover 1 Cr < 5 Cr) -> REJECTED
    buy_proposal = TradeProposal(
        symbol="ILLIQUID",
        requested_notional=50_000.0,
        capital=100_000.0,
        order_side=OrderSide.BUY,
        current_position_notional=0.0,
        daily_turnover_crore=1.0,
    )
    approved, reasons = validator.evaluate(buy_proposal, policy)
    assert approved == 0.0
    assert "insufficient_daily_liquidity" in reasons

    # 2. Pure SELL liquidation of existing 50k long in illiquid stock -> ACCEPTED
    sell_proposal = TradeProposal(
        symbol="ILLIQUID",
        requested_notional=50_000.0,
        capital=100_000.0,
        order_side=OrderSide.SELL,
        current_position_notional=50_000.0,
        daily_turnover_crore=1.0,
    )
    assert sell_proposal.is_pure_risk_reduction is True
    approved_sell, reasons_sell = validator.evaluate(sell_proposal, policy)
    assert approved_sell == 50_000.0
    assert reasons_sell == []
