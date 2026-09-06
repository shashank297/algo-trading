from __future__ import annotations

import pytest

from data_platform.contracts import OrderSide
from trading_stack.costs import (
    TransactionCostConfig,
    TransactionCostCalculator,
)


def test_transaction_cost_calculator_reconciles_all_components_by_side() -> None:
    config = TransactionCostConfig(
        version="test-v1",
        brokerage_bps=10.0,
        brokerage_min=5.0,
        brokerage_max=20.0,
        buy_tax_bps=10.0,
        sell_tax_bps=10.0,
        exchange_bps=0.30699,
        regulatory_bps=0.01,
        other_bps=0.00001,
        buy_fixed=0.0,
        sell_fixed=20.0,
        gst_rate=0.18,
        buy_stamp_bps=1.5,
        spread_bps=2.0,
        slippage_bps=3.0,
        impact_bps_at_full_participation=10.0,
        max_participation=0.05,
    )
    calculator = TransactionCostCalculator(config)

    buy = calculator.calculate(notional=10_000.0, side=OrderSide.BUY, participation=0.01)
    sell = calculator.calculate(notional=10_000.0, side=OrderSide.SELL, participation=0.01)

    assert buy.total == pytest.approx(sum(buy.components.values()))
    assert sell.total == pytest.approx(sum(sell.components.values()))
    assert buy.components["stamp_duty"] > 0
    assert sell.components["stamp_duty"] == 0
    assert sell.components["fixed_charge"] == 20.0
    assert sell.total > buy.total


def test_transaction_cost_calculator_rejects_missing_or_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="version"):
        TransactionCostCalculator(TransactionCostConfig(version=""))

    calculator = TransactionCostCalculator(
        TransactionCostConfig(version="test-v1", allow_zero_costs=True),
    )
    with pytest.raises(ValueError, match="notional"):
        calculator.calculate(notional=-1.0, side=OrderSide.BUY)
    with pytest.raises(ValueError, match="participation"):
        calculator.calculate(notional=100.0, side=OrderSide.BUY, participation=-0.1)


def test_transaction_cost_sensitivity_is_explicit_and_monotonic() -> None:
    base = TransactionCostConfig(version="base", spread_bps=2.0, slippage_bps=3.0)
    stress = base.with_multiplier(2.0, version="stress-2x")

    base_cost = TransactionCostCalculator(base).calculate(100_000.0, OrderSide.BUY).total
    stress_cost = TransactionCostCalculator(stress).calculate(100_000.0, OrderSide.BUY).total

    assert stress.version == "stress-2x"
    assert stress_cost > base_cost
    assert stress.spread_bps == 4.0
    assert stress.slippage_bps == 6.0
