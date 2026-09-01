"""Tests for the multi-market research and backtest stack."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from storage.duckdb_manager import DuckDBManager
from trading_stack.backtest import EventDrivenBacktester, ExecutionModel, PaperBroker, VectorizedBacktester
from trading_stack.calendars import build_default_calendars
from trading_stack.domain import AssetClass, OrderSide
from trading_stack.features import FeatureFactory
from trading_stack.economic import cost_schedule_identity, marked_to_market_equity
from trading_stack.pipeline import StrategyPipeline
from trading_stack.strategies import StrategyRegistry
from utils.timezone import IST


class TradingStackTests(unittest.TestCase):
    """Validate the new research, backtest, and paper-trading primitives."""

    def test_market_calendars_cover_supported_asset_classes(self) -> None:
        """India should have weekday sessions, while crypto stays open daily."""

        calendars = build_default_calendars()
        india_window = calendars[AssetClass.INDIA_EQUITY].session_bounds(date(2026, 8, 17))
        crypto_window = calendars[AssetClass.CRYPTO].session_bounds(date(2026, 8, 17))

        self.assertEqual(india_window.start.tzinfo.key, "Asia/Kolkata")
        self.assertTrue(india_window.start < india_window.end)
        self.assertTrue(crypto_window.start < crypto_window.end)
        self.assertTrue(calendars[AssetClass.CRYPTO].is_trading_day(date(2026, 8, 16)))

    def test_vectorized_backtester_generates_metrics(self) -> None:
        """A trend strategy on rising prices should backtest cleanly."""

        frame = pd.DataFrame(
            {
                "timestamp": pd.date_range(
                    start=datetime(2026, 8, 10, 9, 15, tzinfo=IST),
                    periods=12,
                    freq="D",
                ),
                "symbol": ["NIFTY"] * 12,
                "exchange": ["NSE"] * 12,
                "timeframe": ["1d"] * 12,
                "open": [100 + i for i in range(12)],
                "high": [101 + i for i in range(12)],
                "low": [99 + i for i in range(12)],
                "close": [100.5 + i for i in range(12)],
                "volume": [1000 + i * 10 for i in range(12)],
            },
        )
        features = FeatureFactory().build(frame)
        strategy = StrategyRegistry.create("trend_following", allow_short=False)
        result = VectorizedBacktester().run(
            strategy,
            features,
            symbol="NIFTY",
            timeframe="1d",
            market_asset_class=AssetClass.INDIA_INDEX,
        )

        self.assertEqual(result.symbol, "NIFTY")
        self.assertGreaterEqual(result.metrics.trades, 1)
        self.assertIn("equity", result.equity_curve.columns)
        self.assertFalse(result.orders.empty)
        self.assertFalse(result.fills.empty)

    def test_event_replay_equity_uses_actual_partial_fills(self) -> None:
        frame = pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01", periods=80, freq="D", tz="UTC"),
            "symbol": ["TEST"] * 80, "exchange": ["NSE"] * 80, "timeframe": ["1d"] * 80,
            "open": [100 + value for value in range(80)],
            "high": [101 + value for value in range(80)],
            "low": [99 + value for value in range(80)],
            "close": [100.5 + value for value in range(80)], "volume": [100_000] * 80,
        })
        features = FeatureFactory().build(frame)
        strategy = StrategyRegistry.create("trend_following", allow_short=False)
        full = EventDrivenBacktester(ExecutionModel(exit_on_session_close=False)).run(strategy, features)
        partial = EventDrivenBacktester(ExecutionModel(
            exit_on_session_close=False, allow_partial_fills=True, max_fill_fraction=0.1,
        )).run(strategy, features)

        self.assertNotEqual(full.metrics.total_return, partial.metrics.total_return)
        self.assertLess(abs(partial.metrics.total_return), abs(full.metrics.total_return))
        self.assertIn("PARTIALLY_FILLED", set(partial.orders["status"]))

    def test_intraday_event_replay_exits_each_session(self) -> None:
        class AlwaysLong:
            name = "always_long"

            def validate(self) -> None:
                return None

            def generate_signals(self, bars: pd.DataFrame) -> pd.DataFrame:
                return pd.DataFrame({
                    "timestamp": bars["timestamp"], "target_position": 1.0,
                    "signal": "BUY", "reason": "test",
                })

            def position_sizing(self, signals: pd.DataFrame, portfolio: dict) -> pd.Series:
                return signals["target_position"]

            def risk_constraints(self, portfolio: dict) -> dict:
                return {"max_abs_target_position": 1.0}

        timestamps = pd.to_datetime([
            "2026-08-17T09:15:00+05:30", "2026-08-17T15:29:00+05:30",
            "2026-08-18T09:15:00+05:30", "2026-08-18T15:29:00+05:30",
        ], utc=True)
        bars = pd.DataFrame({
            "timestamp": timestamps, "symbol": "TEST", "open": [100, 101, 102, 103],
            "high": [101, 102, 103, 104], "low": [99, 100, 101, 102],
            "close": [100.5, 101.5, 102.5, 103.5], "volume": 10_000,
        })
        result = EventDrivenBacktester().run(AlwaysLong(), bars, timeframe="1m")

        sell_dates = pd.to_datetime(result.fills[result.fills["side"] == "SELL"]["timestamp"], utc=True).dt.date
        self.assertEqual(len(set(sell_dates)), 2)

    def test_paper_broker_executes_and_reconciles(self) -> None:
        """Paper orders should record both order and fill lifecycle rows."""

        broker = PaperBroker()
        execution = broker.execute_order(
            run_id="run-1",
            symbol="NIFTY",
            side=OrderSide.BUY,
            quantity=10,
            price=100.0,
            timestamp=datetime(2026, 8, 17, 10, 0, tzinfo=IST),
        )
        reconciliation = broker.reconcile(run_id="run-1", trade_date=datetime(2026, 8, 17, 10, 0, tzinfo=IST))

        self.assertEqual(len(broker.orders), 1)
        self.assertEqual(len(broker.fills), 1)
        self.assertIn("order", execution)
        self.assertEqual(reconciliation["submitted_orders"], 1)

        class RejectedDecision:
            action = "REJECT"

        broker.execute_order(
            run_id="run-1", symbol="NIFTY", side=OrderSide.BUY, quantity=10, price=100.0,
            timestamp=datetime(2026, 8, 17, 10, 1, tzinfo=IST), risk_decision=RejectedDecision(),
        )
        reconciliation = broker.reconcile(
            run_id="run-1", trade_date=datetime(2026, 8, 17, 10, 1, tzinfo=IST),
        )
        self.assertEqual(reconciliation["rejected_orders"], 1)

    def test_indian_single_asset_and_paper_costs_use_detailed_schedule(self) -> None:
        costs = {
            "brokerage_rate_bps": 10.0, "brokerage_min": 5.0, "brokerage_max": 20.0,
            "stt_buy_bps": 10.0, "stt_sell_bps": 10.0,
            "exchange_transaction_bps": 0.30699, "sebi_bps": 0.01,
            "ipft_bps": 0.00001, "dp_charge_sell": 20.0,
            "gst_rate": 0.18, "stamp_duty_buy_bps": 1.5,
            "spread_bps": 2.0, "slippage_bps": 3.0,
            "impact_bps_at_full_participation": 10.0,
            "max_volume_participation": 0.05, "minimum_daily_traded_value": 1_000.0,
        }
        model = StrategyPipeline.__new__(StrategyPipeline)._execution_model(costs)
        execution = PaperBroker(model).execute_order(
            run_id="paper-cost", symbol="TEST-EQ", side=OrderSide.BUY,
            quantity=100, price=100.0, timestamp=datetime(2026, 8, 17, tzinfo=IST),
            volume=10_000, close_price=100.0,
        )

        self.assertIsNotNone(model.indian_delivery_costs)
        self.assertGreater(execution["fill"]["fees"], 0)
        self.assertGreater(execution["cost_components"]["stt"], 0)
        self.assertGreater(execution["cost_components"]["stamp_duty"], 0)
        sell = PaperBroker(model).execute_order(
            run_id="paper-cost", symbol="TEST-EQ", side=OrderSide.SELL,
            quantity=100, price=100.0, timestamp=datetime(2026, 8, 17, tzinfo=IST),
            volume=10_000, close_price=100.0,
        )
        self.assertEqual(sell["cost_components"]["dp_charge"], 20.0)
        self.assertGreater(sell["cost_components"]["ipft"], 0)

    def test_strategy_pipeline_persists_run_artifacts(self) -> None:
        """An end-to-end pipeline run should populate the new DuckDB tables."""

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "stack.duckdb")
            db = DuckDBManager(db_path)
            try:
                db.upsert_market_universe(
                    [
                        {
                            "symbol": "NIFTY",
                            "exchange": "NSE",
                            "asset_class": "INDIA_INDEX",
                            "currency": "INR",
                            "timezone": "Asia/Kolkata",
                            "session_open": "09:15",
                            "session_close": "15:30",
                            "tradable": True,
                            "lot_size": 1,
                            "tick_size": 0.05,
                        },
                    ],
                )
                candle_frame = pd.DataFrame(
                    {
                        "timestamp": pd.date_range(
                            start=datetime(2026, 8, 10, 9, 15, tzinfo=IST),
                            periods=10,
                            freq="D",
                        ),
                        "open": [100 + i for i in range(10)],
                        "high": [101 + i for i in range(10)],
                        "low": [99 + i for i in range(10)],
                        "close": [100.5 + i for i in range(10)],
                        "volume": [1000 + i * 10 for i in range(10)],
                    },
                )
                db.upsert_candles(candle_frame, "NIFTY", "26000", "NSE", "1d")

                pipeline = StrategyPipeline(db, require_authoritative_certification=False)
                outcome = pipeline.run(
                    strategy_name="trend_following",
                    symbol="NIFTY",
                    timeframe="1d",
                    mode="vectorized",
                    parameters={"allow_short": False},
                    starting_capital=100_000.0,
                )

                result = outcome["result"]
                run_count = db.conn.execute("SELECT COUNT(*) FROM strategy_runs").fetchone()[0]
                order_count = db.conn.execute("SELECT COUNT(*) FROM strategy_orders").fetchone()[0]
                fill_count = db.conn.execute("SELECT COUNT(*) FROM strategy_fills").fetchone()[0]
                feature_count = db.conn.execute("SELECT COUNT(*) FROM feature_store").fetchone()[0]

                self.assertGreater(result.metrics.trades, 0)
                self.assertEqual(run_count, 1)
                self.assertGreater(order_count, 0)
                self.assertGreater(fill_count, 0)
                self.assertGreater(feature_count, 0)
            finally:
                db.close()

    def test_execution_cost_drag_boundaries(self) -> None:
        """Validate exact execution drag threshold boundary behavior and structured error payloads."""
        from trading_stack.costs import (
            ExecutionReasonCode,
            IndianDeliveryCostSchedule,
            InvalidExecutionPriceError,
            UnexecutableOrderError,
        )

        # Baseline schedule with 500 bps drag limit (spread=2, slippage=3, full_impact=10) -> total=15 bps
        schedule = IndianDeliveryCostSchedule(max_allowed_drag_bps=500.0)

        # Normal execution
        buy_price = schedule.execution_price(100.0, OrderSide.BUY, participation=0.01)
        sell_price = schedule.execution_price(100.0, OrderSide.SELL, participation=0.01)
        self.assertGreater(buy_price, 100.0)
        self.assertLess(sell_price, 100.0)

        # Boundary: drag = 500.0 bps exactly (spread=250, slippage=250, impact=0)
        boundary_schedule = IndianDeliveryCostSchedule(
            spread_bps=250.0,
            slippage_bps=250.0,
            impact_bps_at_full_participation=0.0,
            max_allowed_drag_bps=500.0,
        )
        self.assertEqual(boundary_schedule.execution_price(100.0, OrderSide.BUY, 0.0), 105.0)
        self.assertEqual(boundary_schedule.execution_price(100.0, OrderSide.SELL, 0.0), 95.0)

        # Exceeded: drag = 500.1 bps
        exceeded_schedule = IndianDeliveryCostSchedule(
            spread_bps=250.1,
            slippage_bps=250.0,
            impact_bps_at_full_participation=0.0,
            max_allowed_drag_bps=500.0,
        )
        with self.assertRaises(UnexecutableOrderError) as ctx:
            exceeded_schedule.execution_price(100.0, OrderSide.SELL, 0.0)
        self.assertEqual(ctx.exception.reason_code, ExecutionReasonCode.MAX_EXECUTION_DRAG_EXCEEDED.value)
        self.assertAlmostEqual(ctx.exception.estimated_drag_bps, 500.1, places=3)

        # Invalid price assertions
        with self.assertRaises(InvalidExecutionPriceError):
            schedule.execution_price(-10.0, OrderSide.BUY, 0.0)

        with self.assertRaises(InvalidExecutionPriceError):
            schedule.execution_price(float("nan"), OrderSide.BUY, 0.0)

    def test_metamorphic_session_progress_prefix_invariance(self) -> None:
        """Session progress at 10:00 must be bit-for-bit identical regardless of future bar presence."""
        full_day = pd.DataFrame(
            {
                "timestamp": pd.date_range(
                    start=datetime(2026, 8, 17, 9, 15, tzinfo=IST),
                    end=datetime(2026, 8, 17, 15, 30, tzinfo=IST),
                    freq="1min",
                ),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000.0,
            }
        )

        factory = FeatureFactory()
        full_features = factory.build(full_day, timezone_name="Asia/Kolkata")

        # Truncate dataset unexpectedly at 11:00
        truncated_day = full_day[full_day["timestamp"] <= datetime(2026, 8, 17, 11, 0, tzinfo=IST)].copy()
        truncated_features = factory.build(truncated_day, timezone_name="Asia/Kolkata")

        # Invariance assertion across the complete shared prefix
        shared_timestamps = truncated_features["timestamp"]
        full_shared_progress = full_features.loc[full_features["timestamp"].isin(shared_timestamps), "session_progress"].values
        truncated_progress = truncated_features["session_progress"].values

        pd.testing.assert_series_equal(
            pd.Series(full_shared_progress),
            pd.Series(truncated_progress),
            check_exact=True,
        )

        # Spot checks on regular day session boundaries
        self.assertEqual(full_features.iloc[0]["session_progress"], 0.0)
        self.assertEqual(full_features.iloc[-1]["session_progress"], 1.0)

    def test_session_progress_special_and_out_of_session_bounds(self) -> None:
        """Timestamps outside normal trading session must produce NaN rather than silently clipped values."""
        import numpy as np

        bars = pd.DataFrame(
            {
                "timestamp": [
                    datetime(2026, 8, 17, 8, 30, tzinfo=IST),  # Pre-market before 09:15
                    datetime(2026, 8, 17, 9, 15, tzinfo=IST),  # Session open -> 0.0
                    datetime(2026, 8, 17, 12, 22, 30, tzinfo=IST),  # Mid session -> ~0.5
                    datetime(2026, 8, 17, 15, 30, tzinfo=IST),  # Session close -> 1.0
                    datetime(2026, 8, 17, 17, 0, tzinfo=IST),  # Post-market after 15:30
                ],
                "open": [100.0] * 5,
                "high": [101.0] * 5,
                "low": [99.0] * 5,
                "close": [100.5] * 5,
                "volume": [1000.0] * 5,
            }
        )
        factory = FeatureFactory()
        features = factory.build(bars, timezone_name="Asia/Kolkata")

        self.assertTrue(np.isnan(features.iloc[0]["session_progress"]))  # 08:30 is NaN
        self.assertAlmostEqual(features.iloc[1]["session_progress"], 0.0)
        self.assertAlmostEqual(features.iloc[2]["session_progress"], 0.5, places=2)
        self.assertAlmostEqual(features.iloc[3]["session_progress"], 1.0)
        self.assertTrue(np.isnan(features.iloc[4]["session_progress"]))  # 17:00 is NaN

    def test_backtest_paper_execution_policy_parity(self) -> None:
        """PaperBroker and IndianDeliveryCostSchedule must produce matching economics for identical trades."""
        from trading_stack.costs import IndianDeliveryCostSchedule

        schedule = IndianDeliveryCostSchedule()
        exec_model = ExecutionModel(indian_delivery_costs={})
        broker = PaperBroker(exec_model)


        price = 1000.0
        qty = 50.0
        vol = 10_000.0
        ts = datetime(2026, 8, 17, 10, 0, tzinfo=IST)

        # BUY order
        buy_result = broker.execute_order(
            run_id="parity-buy",
            symbol="TEST-EQ",
            side=OrderSide.BUY,
            quantity=qty,
            price=price,
            timestamp=ts,
            volume=vol,
        )
        expected_participation = qty / vol
        expected_buy_price = schedule.execution_price(price, OrderSide.BUY, expected_participation)
        expected_breakdown = schedule.calculate(qty * expected_buy_price, OrderSide.BUY, expected_participation)

        self.assertEqual(buy_result["order"]["status"], "FILLED")
        self.assertAlmostEqual(buy_result["fill"]["price"], expected_buy_price, places=4)
        self.assertAlmostEqual(buy_result["order"]["fees"], expected_breakdown.statutory_and_broker_fees, places=4)

        # SELL order
        sell_result = broker.execute_order(
            run_id="parity-sell",
            symbol="TEST-EQ",
            side=OrderSide.SELL,
            quantity=qty,
            price=price,
            timestamp=ts,
            volume=vol,
        )
        expected_sell_price = schedule.execution_price(price, OrderSide.SELL, expected_participation)
        expected_sell_breakdown = schedule.calculate(qty * expected_sell_price, OrderSide.SELL, expected_participation)

        self.assertEqual(sell_result["order"]["status"], "FILLED")
        self.assertAlmostEqual(sell_result["fill"]["price"], expected_sell_price, places=4)
        self.assertAlmostEqual(sell_result["order"]["fees"], expected_sell_breakdown.statutory_and_broker_fees, places=4)

    def test_economic_conservation_across_trade_sequence(self) -> None:
        """Fill-ledger cash and holdings must conserve account equity."""

        from trading_stack.costs import IndianDeliveryCostSchedule

        schedule = IndianDeliveryCostSchedule()
        broker = PaperBroker(ExecutionModel(indian_delivery_costs=asdict(schedule)))
        cash = 100_000.0
        quantity = 0.0

        def trade(side: OrderSide, requested: float, price: float, volume: float) -> dict:
            nonlocal cash, quantity
            result = broker.execute_order(
                run_id="conservation",
                symbol="TEST-EQ",
                side=side,
                quantity=requested,
                price=price,
                timestamp=datetime(2026, 8, 17, 10, 0, tzinfo=IST),
                volume=volume,
                close_price=price,
                available_cash=cash if side == OrderSide.BUY else None,
            )
            fill = result["fill"]
            if fill is not None:
                notional = float(fill["quantity"]) * float(fill["price"])
                fees = float(fill["fees"])
                if side == OrderSide.BUY:
                    cash -= notional + fees
                    quantity += float(fill["quantity"])
                else:
                    cash += notional - fees
                    quantity -= float(fill["quantity"])
                self.assertGreaterEqual(cash, -1e-8)
            return result

        trade(OrderSide.BUY, 10.0, 100.0, 1_000.0)
        self.assertAlmostEqual(marked_to_market_equity(cash, {"TEST-EQ": quantity}, {"TEST-EQ": 105.0}), cash + quantity * 105.0)
        partial_buy = trade(OrderSide.BUY, 1_000.0, 101.0, 10_000.0)
        self.assertEqual(partial_buy["order"]["status"], "PARTIALLY_FILLED")
        trade(OrderSide.SELL, 3.0, 110.0, 1_000.0)
        trade(OrderSide.SELL, quantity, 108.0, 10_000.0)
        self.assertAlmostEqual(quantity, 0.0)
        self.assertAlmostEqual(marked_to_market_equity(cash, {"TEST-EQ": quantity}, {"TEST-EQ": 108.0}), cash)

    def test_cost_identity_binds_all_date_effective_regimes(self) -> None:
        """Historical cost identity must change when a covered regime changes."""

        from trading_stack.costs import get_cost_schedule

        one_regime = cost_schedule_identity(
            [date(2025, 1, 2), date(2025, 2, 3)], get_cost_schedule,
        )
        two_regimes = cost_schedule_identity(
            [date(2025, 1, 2), date(2026, 8, 3)], get_cost_schedule,
        )
        self.assertNotEqual(one_regime, two_regimes)


if __name__ == "__main__":
    unittest.main()
