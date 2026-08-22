"""Tests for dual-scope strategies, portfolio replay, costs, and RCA."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

from storage import DuckDBManager
from main import load_index_benchmark_symbol, load_universe_snapshot_symbols, latest_completed_daily_session
from experiments.walk_forward import WalkForwardEvaluator, WalkForwardRecorder
from experiments.models import ExperimentSpec, MassExperimentSpec
from experiments.mass import MassExperimentManager
from trading_stack.costs import IndianDeliveryCostSchedule
from trading_stack.datasets import ResearchDataset, SynchronizedPanelBuilder
from trading_stack.domain import BacktestMetrics, OrderSide, StrategyScope, StrategyMetadata
from trading_stack.portfolio import PortfolioEventBacktester
from trading_stack.promotion import PromotionEngine
from trading_stack.rca import RCAEngine
from trading_stack.strategies import StrategyRegistry
from trading_stack.universe import UniverseResearchService
from trading_stack.calendars import MarketCalendar, SessionOverride, build_nse_calendar
from trading_stack.domain import infer_market_spec
from trading_stack.pipeline import StrategyPipeline
from trading_stack.paper import ForwardPaperSessionEngine
from trading_stack.portfolio_paper import ForwardPortfolioPaperSessionEngine
from trading_stack.features import FeatureFactory
from risk import RiskEngine, RiskPolicy
from utils.timezone import IST


def panel_fixture(periods: int = 320, symbols: int = 6) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=periods, freq="B", tz="UTC")
    frames = []
    for index in range(symbols):
        trend = 0.03 + index * 0.02
        close = 100 + index + np.arange(periods) * trend + np.sin(np.arange(periods) / 10 + index)
        frames.append(pd.DataFrame({
            "timestamp": dates, "symbol": f"STOCK{index}", "exchange": "NSE", "timeframe": "1d",
            "open": close - 0.1, "high": close + 1.0, "low": close - 1.0, "close": close,
            "volume": 200_000 + index * 10_000, "benchmark_close": 100 + np.arange(periods) * 0.04,
            "sector": f"SECTOR{index % 2}",
        }))
    return pd.concat(frames, ignore_index=True)


class MultiStrategyPlatformTests(unittest.TestCase):
    def test_verified_weekend_special_session_is_a_trading_day(self) -> None:
        special_date = date(2026, 2, 1)
        calendar = MarketCalendar(
            infer_market_spec("INDIA_EQUITY", "NSE", "EQUITY"),
            overrides=(SessionOverride(
                session_date=special_date,
                override_type="SPECIAL_SESSION",
                reason="NSE CMTR72349",
            ),),
        )

        self.assertTrue(calendar.is_trading_day(special_date))

    def test_nse_calendar_preserves_configured_evidence_version(self) -> None:
        calendar = build_nse_calendar(version="nse-evidence-test-v1")

        self.assertEqual(calendar.version, "nse-evidence-test-v1")

    def test_cross_sectional_paper_is_forward_only_and_uses_synchronized_next_session(self) -> None:
        source = panel_fixture(periods=260, symbols=6)
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "portfolio-paper.duckdb"))
            try:
                for symbol, bars in source.groupby("symbol"):
                    db.upsert_candles(
                        bars[["timestamp", "open", "high", "low", "close", "volume"]],
                        str(symbol), str(symbol), "NSE", "1d",
                    )
                benchmark = source[source["symbol"] == "STOCK0"][
                    ["timestamp", "open", "high", "low", "close", "volume"]
                ].copy()
                benchmark_close = source[source["symbol"] == "STOCK0"]["benchmark_close"].to_numpy()
                for column in ("open", "high", "low", "close"):
                    benchmark[column] = benchmark_close
                db.upsert_candles(benchmark, "NIFTY200", "INDEX", "NSE", "1d")
                calendar = MarketCalendar(infer_market_spec("INDIA_EQUITY", "NSE", "EQUITY"))
                engine = ForwardPortfolioPaperSessionEngine(
                    db,
                    calendar=calendar,
                    risk_engine=RiskEngine(),
                    require_authoritative_certification=False,
                )
                symbols = sorted(source["symbol"].unique().tolist())
                last_timestamp = pd.Timestamp(source["timestamp"].max())
                first = engine.run(
                    strategy_name="cross_sectional_momentum", approved_run_id="approved-portfolio",
                    symbols=symbols, universe_snapshot_id="CONFIGURED_UNIVERSE", benchmark_symbol="NIFTY200",
                    timeframe="1d", as_of=(last_timestamp + pd.Timedelta(hours=12)).to_pydatetime(),
                )

                next_timestamp = last_timestamp + pd.offsets.BDay(1)
                for index, symbol in enumerate(symbols):
                    price = 120.0 + index
                    db.upsert_candles(pd.DataFrame({
                        "timestamp": [next_timestamp], "open": [price], "high": [price + 1],
                        "low": [price - 1], "close": [price + 0.2], "volume": [200_000],
                    }), symbol, symbol, "NSE", "1d")
                db.upsert_candles(pd.DataFrame({
                    "timestamp": [next_timestamp], "open": [120.0], "high": [121.0],
                    "low": [119.0], "close": [120.2], "volume": [200_000],
                }), "NIFTY200", "INDEX", "NSE", "1d")
                second = engine.run(
                    strategy_name="cross_sectional_momentum", approved_run_id="approved-portfolio",
                    symbols=symbols, universe_snapshot_id="CONFIGURED_UNIVERSE", benchmark_symbol="NIFTY200",
                    timeframe="1d", as_of=(next_timestamp + pd.Timedelta(hours=12)).to_pydatetime(),
                )
                held_symbol = str(db.conn.execute(
                    "SELECT symbol FROM paper_portfolio_holdings ORDER BY symbol LIMIT 1"
                ).fetchone()[0])
                third_timestamp = next_timestamp + pd.offsets.BDay(1)
                for index, symbol in enumerate(symbols):
                    if symbol == held_symbol:
                        continue
                    price = 121.0 + index
                    db.upsert_candles(pd.DataFrame({
                        "timestamp": [third_timestamp], "open": [price], "high": [price + 1],
                        "low": [price - 1], "close": [price + 0.2], "volume": [200_000],
                    }), symbol, symbol, "NSE", "1d")
                db.upsert_candles(pd.DataFrame({
                    "timestamp": [third_timestamp], "open": [121.0], "high": [122.0],
                    "low": [120.0], "close": [121.2], "volume": [200_000],
                }), "NIFTY200", "INDEX", "NSE", "1d")
                third = engine.run(
                    strategy_name="cross_sectional_momentum", approved_run_id="approved-portfolio",
                    symbols=symbols, universe_snapshot_id="CONFIGURED_UNIVERSE", benchmark_symbol="NIFTY200",
                    timeframe="1d", as_of=(third_timestamp + pd.Timedelta(hours=12)).to_pydatetime(),
                )
            finally:
                db.close()

        self.assertEqual(first.status, "BOOTSTRAPPED")
        self.assertEqual(len(first.orders), 0)
        self.assertEqual(second.status, "PROCESSED")
        self.assertEqual(second.processed_sessions, 1)
        self.assertGreater(len(second.fills), 0)
        self.assertTrue(all(pd.Timestamp(fill["timestamp"]) == next_timestamp for fill in second.fills))
        self.assertEqual(third.status, "PROCESSED")
        self.assertEqual(third.processed_sessions, 1)

    def test_portfolio_paper_risk_allows_replacement_after_planned_sales(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "paper-rotation.duckdb"))
            try:
                engine = ForwardPortfolioPaperSessionEngine(
                    db,
                    calendar=MarketCalendar(infer_market_spec("INDIA_EQUITY", "NSE", "EQUITY")),
                    risk_engine=RiskEngine(),
                    require_authoritative_certification=False,
                )
                timestamp = pd.Timestamp("2026-08-17", tz="UTC")
                symbols = ["EXIT", "KEEP1", "KEEP2", "KEEP3", "ENTER"]
                day = pd.DataFrame({
                    "symbol": symbols, "open": [100.0] * 5, "close": [100.0] * 5,
                    "volume": [200_000] * 5,
                }).set_index("symbol", drop=False)
                targets = pd.DataFrame({
                    "timestamp": [timestamp] * 5, "symbol": symbols,
                    "target_weight": [0.0, 0.05, 0.05, 0.05, 0.05],
                    "rank": [5, 1, 2, 3, 4],
                })
                adjusted, decisions = engine._risk_adjust_targets(
                    targets, day,
                    {"EXIT": 50.0, "KEEP1": 50.0, "KEEP2": 50.0, "KEEP3": 50.0},
                    80_000.0, {symbol: 100.0 for symbol in symbols}, 100_000.0,
                    100_000.0, 100_000.0,
                )
            finally:
                db.close()

        enter_weight = float(adjusted.loc[adjusted["symbol"] == "ENTER", "target_weight"].iloc[0])
        self.assertAlmostEqual(enter_weight, 0.05)
        self.assertTrue(any(decision.reasons == ["risk_reducing_exit"] for decision in decisions))

    def test_daily_ingestion_uses_latest_completed_session_before_market_close(self) -> None:
        calendar = MarketCalendar(infer_market_spec("INDIA_EQUITY", "NSE", "EQUITY"))

        completed = latest_completed_daily_session(
            calendar,
            datetime(2026, 8, 18, 0, 15, tzinfo=IST),
            datetime.strptime("15:30", "%H:%M").time(),
        )

        self.assertEqual(completed, date(2026, 8, 17))

    def test_exact_nifty200_benchmark_resolves_from_instrument_master(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "benchmark.duckdb"))
            try:
                db.conn.execute(
                    """INSERT INTO instrument_master
                       (token, symbol, name, instrumenttype, exch_seg)
                       VALUES ('99926033', 'Nifty 200', 'NIFTY 200', 'AMXIDX', 'NSE')""",
                )
                benchmark = load_index_benchmark_symbol(db, "NIFTY200")
            finally:
                db.close()

        self.assertEqual(benchmark["symbol"], "NIFTY200")
        self.assertEqual(benchmark["token"], "99926033")

    def test_nifty200_readiness_requires_complete_snapshot_data_and_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "nifty200.duckdb"))
            try:
                db._replace_rows("universe_snapshots", [{
                    "snapshot_id": "NIFTY200_TEST", "name": "NIFTY 200",
                    "source_url": "https://example.test/nifty200.csv", "effective_date": date(2026, 8, 17),
                    "content_hash": "verified", "survivorship_bias": True,
                }])
                members = [{
                    "snapshot_id": "NIFTY200_TEST", "symbol": f"S{index:03d}",
                    "provider_symbol": f"S{index:03d}-EQ", "provider_token": str(index + 1),
                    "company_name": f"Stock {index}", "sector": "TEST", "exchange": "NSE",
                    "active_from": date(2026, 8, 17), "active_to": None,
                    "liquidity_eligible": True, "data_eligible": True, "paper_eligible": True,
                } for index in range(200)]
                db._replace_rows("universe_snapshot_members", members)
                bars = pd.DataFrame({
                    "timestamp": pd.date_range("2026-08-13", periods=2, freq="B", tz=IST),
                    "open": [100.0, 101.0], "high": [101.0, 102.0], "low": [99.0, 100.0],
                    "close": [100.5, 101.5], "volume": [100_000, 100_000],
                })
                for member in members:
                    db.upsert_candles(bars, member["provider_symbol"], member["provider_token"], "NSE", "1d")
                db.upsert_candles(bars, "NIFTY", "26000", "NSE", "1d")
                db.conn.execute(
                    """INSERT INTO quality_report
                       (symbol, timeframe, check_type, issue_count, details, checked_at)
                       VALUES ('UNRELATED-EQ', '1d', 'session_alignment', 99, '{}', CURRENT_TIMESTAMP)"""
                )
                readiness = UniverseResearchService(db).readiness("NIFTY200_TEST", minimum_bars=2)
            finally:
                db.close()

        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.member_count, 200)
        self.assertEqual(readiness.symbols_with_lookback, 200)

    def test_calendar_excludes_declared_market_interruption(self) -> None:
        calendar = MarketCalendar(
            infer_market_spec("INDIA_EQUITY", "NSE", "EQUITY"),
            overrides=(SessionOverride(
                date(2026, 8, 17), "INTERRUPTION", "exchange halt",
                start_time=datetime.strptime("09:20", "%H:%M").time(),
                end_time=datetime.strptime("09:25", "%H:%M").time(),
            ),),
            version="test-v1", verified_through=date(2026, 8, 17),
        )

        expected = calendar.expected_minute_index(date(2026, 8, 17), date(2026, 8, 17))

        self.assertNotIn(pd.Timestamp("2026-08-17 09:22", tz=IST), expected)
        self.assertIn(pd.Timestamp("2026-08-17 09:25", tz=IST), expected)

    def test_forward_paper_bootstraps_without_replay_then_processes_new_bar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "paper.duckdb"))
            try:
                initial_close = np.arange(100, 160, dtype=float)
                initial = pd.DataFrame({
                    "timestamp": pd.bdate_range(end="2026-08-13", periods=60, tz=IST),
                    "open": initial_close, "high": initial_close + 1,
                    "low": initial_close - 1, "close": initial_close + 0.5,
                    "volume": [100_000] * 60,
                })
                db.upsert_candles(initial, "TEST-EQ", "1", "NSE", "1d")
                db._replace_rows("promotion_reviews", [{
                    "review_id": "paper-approval", "strategy_name": "trend_following",
                    "run_id": "approved-run", "stage": "PAPER_ACTIVE", "decision": "PASS",
                    "score": 1.0, "reasons_json": "[]", "human_approved": True,
                    "reviewed_at": datetime.now(timezone.utc),
                }])
                pipeline = StrategyPipeline(db, require_authoritative_certification=False)
                first = pipeline.run_paper_session(
                    strategy_name="trend_following", approved_run_id="approved-run",
                    symbol="TEST-EQ", timeframe="1d",
                    as_of=datetime(2026, 8, 13, 16, 0, tzinfo=IST),
                )["forward_result"]
                next_bar = pd.DataFrame({
                    "timestamp": [datetime(2026, 8, 14, tzinfo=IST)], "open": [160], "high": [161],
                    "low": [159], "close": [160.5], "volume": [100_000],
                })
                db.upsert_candles(next_bar, "TEST-EQ", "1", "NSE", "1d")
                second = pipeline.run_paper_session(
                    strategy_name="trend_following", approved_run_id="approved-run",
                    symbol="TEST-EQ", timeframe="1d",
                    as_of=datetime(2026, 8, 14, 16, 0, tzinfo=IST),
                )["forward_result"]
                risk_count = db.conn.execute("SELECT COUNT(*) FROM risk_decisions").fetchone()[0]
            finally:
                db.close()

        self.assertEqual(first.status, "BOOTSTRAPPED")
        self.assertEqual(len(first.orders), 0)
        self.assertEqual(second.processed_bars, 1)
        self.assertTrue(all(pd.Timestamp(fill["timestamp"]) > pd.Timestamp(first.pending_signal_timestamp) for fill in second.fills))
        self.assertGreater(risk_count, 0)

    def test_forward_paper_rejects_unapproved_research_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "unapproved-paper.duckdb"))
            try:
                bars = panel_fixture(periods=30, symbols=1).drop(
                    columns=["symbol", "exchange", "timeframe", "benchmark_close", "sector"],
                )
                db.upsert_candles(bars, "TEST-EQ", "1", "NSE", "1d")
                with self.assertRaisesRegex(PermissionError, "No promotion review"):
                    StrategyPipeline(db, require_authoritative_certification=False).run_paper_session(
                        strategy_name="trend_following",
                        approved_run_id="unapproved-run",
                        symbol="TEST-EQ",
                        timeframe="1d",
                    )
            finally:
                db.close()

    def test_research_rejects_bars_beyond_verified_calendar_horizon(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "calendar-horizon.duckdb"))
            try:
                bars = pd.DataFrame({
                    "timestamp": [pd.Timestamp("2026-08-18 09:15", tz=IST)],
                    "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5],
                    "volume": [100_000],
                })
                db.upsert_candles(bars, "TEST-EQ", "1", "NSE", "1d")
                pipeline = StrategyPipeline(
                    db,
                    india_calendar=build_nse_calendar(verified_through=date(2026, 8, 17)),
                    require_authoritative_certification=False,
                )
                with self.assertRaisesRegex(ValueError, "verified only through"):
                    pipeline.run(
                        strategy_name="trend_following", symbol="TEST-EQ", timeframe="1d",
                    )
            finally:
                db.close()

    def test_forward_paper_persists_daily_loss_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "paper-risk.duckdb"))
            try:
                engine = ForwardPaperSessionEngine(
                    db,
                    calendar=MarketCalendar(infer_market_spec("INDIA_EQUITY", "NSE", "EQUITY")),
                    risk_engine=RiskEngine(RiskPolicy(max_daily_loss_pct=0.01)),
                )
                pending = {
                    "target_position": 1.0, "signal_timestamp": pd.Timestamp("2026-08-17", tz="UTC"),
                    "reason": "test",
                }
                _, _, _, _, _, _, _, order, fill, _, _, decision = engine._execute_pending(
                    "paper-test", "TEST-EQ",
                    {"timestamp": pd.Timestamp("2026-08-18", tz="UTC"), "open": 100.0},
                    pending, 98_000.0, 0.0, 0.0, 100_000.0, 100_000.0, 100_000.0,
                )
            finally:
                db.close()
        self.assertEqual(order["status"], "REJECTED")
        self.assertIsNone(fill)
        self.assertEqual(decision.action.value, "REJECT")

    def test_single_asset_pipeline_persists_realized_attribution_and_cost(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "attribution.duckdb"))
            try:
                close = np.r_[np.arange(100, 160), np.arange(160, 90, -1)]
                bars = pd.DataFrame({
                    "timestamp": pd.date_range("2026-01-01", periods=len(close), freq="B", tz=IST),
                    "open": close, "high": close + 1, "low": close - 1, "close": close,
                    "volume": [100_000] * len(close),
                })
                db.upsert_candles(bars, "TEST-EQ", "1", "NSE", "1d")
                outcome = StrategyPipeline(db, require_authoritative_certification=False).run(
                    strategy_name="trend_following", symbol="TEST-EQ", timeframe="1d",
                    mode="event-driven",
                    cost_model={"fee_bps": 2.0, "slippage_bps": 3.0, "spread_bps": 2.0},
                )
                rerun = StrategyPipeline(db, require_authoritative_certification=False).run(
                    strategy_name="trend_following", symbol="TEST-EQ", timeframe="1d",
                    mode="event-driven",
                    cost_model={"fee_bps": 2.0, "slippage_bps": 3.0, "spread_bps": 2.0},
                )
                persisted_fills = db.conn.execute(
                    "SELECT COUNT(*) FROM strategy_fills WHERE run_id = ?",
                    [outcome["result"].run_id],
                ).fetchone()[0]
                evidence = db.conn.execute(
                    "SELECT COUNT(*), SUM(cost), SUM(gross_pnl) FROM trade_attribution WHERE run_id = ?",
                    [outcome["result"].run_id],
                ).fetchone()
                round_trip = db.conn.execute(
                    "SELECT COUNT(*), SUM(gross_pnl), SUM(entry_cost + exit_cost), SUM(net_pnl) FROM trade_round_trips WHERE run_id = ?",
                    [outcome["result"].run_id],
                ).fetchone()
                explanation = RCAEngine(db).explain_loss(
                    outcome["result"].run_id, evidence_level="IN_SAMPLE",
                )
            finally:
                db.close()

        self.assertGreater(evidence[0], 0)
        self.assertEqual(persisted_fills, len(rerun["result"].fills))
        self.assertGreater(evidence[1], 0)
        self.assertNotEqual(evidence[2], 0)
        self.assertGreater(explanation["causes"][0]["cost"], 0)
        self.assertGreater(round_trip[0], 0)
        self.assertAlmostEqual(round_trip[3], round_trip[1] - round_trip[2], places=8)
        self.assertEqual(len(explanation["round_trips"]), round_trip[0])
    def test_mass_experiment_accepts_versioned_cost_schedule(self) -> None:
        spec = MassExperimentSpec(
            strategy_names=["trend_following"],
            universe=["RELIANCE-EQ"],
            cost_model={"version": "angel-nse-delivery-2026-04", "brokerage_rate_bps": 10.0},
        )

        self.assertEqual(spec.cost_model["version"], "angel-nse-delivery-2026-04")

    def test_mass_job_key_separates_execution_mode_and_timeframe(self) -> None:
        arguments = ("trend_following", "1.0.0", "SINGLE_ASSET", ["RELIANCE-EQ"], "SNAPSHOT", {}, "cost-v1", "source-v1", 252, 63)

        vectorized = MassExperimentManager._job_key(*arguments, "1d", "vectorized")
        event_driven = MassExperimentManager._job_key(*arguments, "1d", "event-driven")
        intraday = MassExperimentManager._job_key(*arguments, "1m", "event-driven")

        self.assertEqual(len({vectorized, event_driven, intraday}), 3)

    def test_mass_job_key_changes_with_market_data_revision(self) -> None:
        arguments = ("trend_following", "1.0.0", "SINGLE_ASSET", ["RELIANCE-EQ"], "SNAPSHOT", {}, "cost-v1", "source-v1", 252, 63, "1d", "event-driven")

        self.assertNotEqual(
            MassExperimentManager._job_key(*arguments, data_revision=1),
            MassExperimentManager._job_key(*arguments, data_revision=2),
        )

    def test_mass_runner_retries_failed_job_within_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "retry.duckdb"))
            try:
                successful = {"outcome": {"result": SimpleNamespace(run_id="run-1")}}
                with patch("experiments.mass.ExperimentManager.run", side_effect=[RuntimeError("transient"), successful]), patch.object(WalkForwardEvaluator, "evaluate", return_value=[]):
                    result = MassExperimentManager(db).run(MassExperimentSpec(
                        strategy_names=["trend_following"], universe=["TEST-EQ"],
                        benchmark_symbol=None, max_retries=1,
                    ))
                job = db.conn.execute("SELECT state, retry_count FROM experiment_jobs").fetchone()
            finally:
                db.close()

        self.assertEqual(result["jobs"][0]["state"], "SUCCEEDED")
        self.assertEqual(job, ("SUCCEEDED", 1))

    def test_mass_runner_executes_two_isolated_workers_against_one_duckdb(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "parallel-mass.duckdb"))
            try:
                bars = panel_fixture(periods=180, symbols=2)
                symbols = []
                for symbol, frame in bars.groupby("symbol"):
                    symbols.append(str(symbol))
                    db.upsert_candles(
                        frame[["timestamp", "open", "high", "low", "close", "volume"]],
                        str(symbol), str(symbol), "NSE", "1d",
                    )
                result = MassExperimentManager(db).run(MassExperimentSpec(
                    strategy_names=["trend_following"], universe=symbols,
                    benchmark_symbol=None, max_workers=2, mode="event-driven",
                    walk_forward_train_size=80, walk_forward_test_size=40,
                    require_authoritative_certification=False,
                ))
            finally:
                db.close()

        self.assertEqual(len(result["jobs"]), 2)
        self.assertTrue(all(job["state"] == "SUCCEEDED" for job in result["jobs"]))

    def test_stale_and_superseded_jobs_reach_terminal_or_retry_states(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "recovery.duckdb"))
            try:
                base = {
                    "experiment_id": "mass", "strategy_name": "trend_following",
                    "strategy_version": "1.0.0", "strategy_scope": "SINGLE_ASSET",
                    "symbol": "TEST-EQ", "parameters_hash": "params",
                    "cost_model_version": "cost", "max_retries": 2,
                    "source_revision": "old", "data_revision": 1,
                }
                db.log_experiment_job({
                    **base, "job_key": "running", "state": "RUNNING", "retry_count": 0,
                    "started_at": datetime.now(timezone.utc) - timedelta(hours=2),
                })
                db.log_experiment_job({**base, "job_key": "pending", "state": "PENDING"})
                recovered = db.recover_stale_research_work(datetime.now(timezone.utc) - timedelta(hours=1))
                cancelled = db.cancel_superseded_experiment_jobs("new", 2)
                states = dict(db.conn.execute("SELECT job_key, state FROM experiment_jobs").fetchall())
            finally:
                db.close()
        self.assertEqual(recovered["jobs"], 1)
        self.assertEqual(cancelled, 2)
        self.assertEqual(states, {"running": "CANCELLED", "pending": "CANCELLED"})

    def test_dataset_hash_and_cache_change_with_research_inputs(self) -> None:
        original = ResearchDataset("TEST", {"AAA": "one"}, panel_fixture(periods=30, symbols=1))
        changed_panel = original.panel.copy()
        changed_panel["sector"] = "DIFFERENT"
        changed = ResearchDataset("TEST", {"AAA": "two"}, changed_panel)
        self.assertNotEqual(original.data_hash, changed.data_hash)

        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "cache.duckdb"))
            try:
                bars = panel_fixture(periods=10, symbols=1).drop(columns=["symbol", "exchange", "timeframe", "benchmark_close", "sector"])
                db.upsert_candles(bars.iloc[:5], "STOCK0", "1", "NSE", "1d")
                first = SynchronizedPanelBuilder(db, require_authoritative_certification=False).build(["STOCK0"], "1d", benchmark_symbol=None)
                db.upsert_candles(bars.iloc[5:], "STOCK0", "1", "NSE", "1d")
                second = SynchronizedPanelBuilder(db, require_authoritative_certification=False).build(["STOCK0"], "1d", benchmark_symbol=None)
            finally:
                db.close()
        self.assertEqual(len(first.panel), 5)
        self.assertEqual(len(second.panel), 10)

    def test_run_identity_separates_parameters_costs_and_modes(self) -> None:
        bars = panel_fixture(periods=80, symbols=1)
        single = FeatureFactory().build(bars[bars["symbol"] == "STOCK0"])
        from trading_stack.backtest import EventDrivenBacktester, ExecutionModel
        run_a = EventDrivenBacktester(ExecutionModel(fee_bps=1)).run(
            StrategyRegistry.create("trend_following", fast_threshold=0.01), single,
            symbol="STOCK0", parameters={"fast_threshold": 0.01},
        )
        run_b = EventDrivenBacktester(ExecutionModel(fee_bps=2)).run(
            StrategyRegistry.create("trend_following", fast_threshold=0.01), single,
            symbol="STOCK0", parameters={"fast_threshold": 0.01},
        )
        run_c = EventDrivenBacktester(ExecutionModel(fee_bps=1)).run(
            StrategyRegistry.create("trend_following", fast_threshold=0.02), single,
            symbol="STOCK0", parameters={"fast_threshold": 0.02},
        )
        dataset = ResearchDataset("TEST", {}, panel_fixture())
        portfolio_a = PortfolioEventBacktester().run(StrategyRegistry.create("cross_sectional_momentum"), dataset, mode="event-driven")
        portfolio_b = PortfolioEventBacktester().run(StrategyRegistry.create("cross_sectional_momentum"), dataset, mode="paper")
        self.assertNotEqual(run_a.run_id, run_b.run_id)
        self.assertNotEqual(run_a.run_id, run_c.run_id)
        self.assertNotEqual(portfolio_a.run.run_id, portfolio_b.run.run_id)

    def test_registry_discovers_twenty_delivery_strategies_plus_compatibility_strategy(self) -> None:
        names = StrategyRegistry.available()
        promotable = [name for name in names if StrategyRegistry.metadata(name).paper_eligible]

        self.assertEqual(len(names), 21)
        self.assertEqual(len(promotable), 20)
        self.assertFalse(StrategyRegistry.metadata("opening_range_breakout").paper_eligible)
        self.assertEqual(StrategyRegistry.metadata("cross_sectional_momentum").scope, StrategyScope.CROSS_SECTIONAL)

    def test_all_non_ml_strategies_honor_the_normalized_signal_contract(self) -> None:
        panel = panel_fixture()
        for name in StrategyRegistry.available():
            if name == "opening_range_breakout":
                continue
            strategy = StrategyRegistry.create(name)
            if name == "walk_forward_logistic":
                strategy = StrategyRegistry.create(name, minimum_training_rows=100)
            source = panel if strategy.metadata.scope == StrategyScope.CROSS_SECTIONAL else panel[panel["symbol"] == "STOCK0"]
            signals = strategy.generate_signals(source)
            self.assertTrue({"timestamp", "symbol", "target_weight", "signal", "reason", "score", "rank", "feature_snapshot"}.issubset(signals.columns), name)
            self.assertTrue((signals["target_weight"] >= 0).all(), name)

    def test_cross_sectional_ranks_do_not_change_when_future_prices_change(self) -> None:
        panel = panel_fixture()
        strategy = StrategyRegistry.create("cross_sectional_momentum")
        original = strategy.generate_signals(panel)
        cutoff = original["timestamp"].sort_values().iloc[0]
        changed = panel.copy()
        changed.loc[changed["timestamp"] > cutoff, "close"] *= 10
        revised = strategy.generate_signals(changed)

        columns = ["timestamp", "symbol", "target_weight", "rank"]
        pd.testing.assert_frame_equal(
            original[original["timestamp"] <= cutoff][columns].reset_index(drop=True),
            revised[revised["timestamp"] <= cutoff][columns].reset_index(drop=True),
        )

    def test_portfolio_replay_executes_on_next_session_and_respects_exposure(self) -> None:
        panel = panel_fixture()
        dataset = ResearchDataset("TEST", {}, panel)
        result = PortfolioEventBacktester().run(StrategyRegistry.create("cross_sectional_momentum"), dataset)

        self.assertFalse(result.run.fills.empty)
        first_signal = result.run.signals[result.run.signals["target_weight"] > 0]["timestamp"].min()
        first_fill = result.run.fills["timestamp"].min()
        self.assertGreater(first_fill, first_signal)
        portfolio_rows = result.positions[result.positions["symbol"] == "__PORTFOLIO__"]
        self.assertLessEqual(float(portfolio_rows["gross_exposure"].max()), 0.200001)
        self.assertTrue((portfolio_rows["cash"] >= 0).all())
        self.assertFalse(result.round_trips.empty)
        self.assertTrue((result.round_trips["exit_timestamp"] > result.round_trips["entry_timestamp"]).all())
        reconciled = result.round_trips["gross_pnl"] - result.round_trips["entry_cost"] - result.round_trips["exit_cost"]
        self.assertTrue(np.allclose(result.round_trips["net_pnl"], reconciled))
        self.assertGreaterEqual(result.run.metrics.win_rate, 0.0)
        self.assertLessEqual(result.run.metrics.win_rate, 1.0)

    def test_indian_delivery_costs_are_side_aware(self) -> None:
        schedule = IndianDeliveryCostSchedule()
        buy = schedule.calculate(100_000, OrderSide.BUY)
        sell = schedule.calculate(100_000, OrderSide.SELL)

        self.assertGreater(buy.stamp_duty, 0)
        self.assertEqual(sell.stamp_duty, 0)
        self.assertGreater(buy.stt, 0)
        self.assertGreater(sell.stt, 0)
        self.assertEqual(buy.dp_charge, 0)
        self.assertEqual(sell.dp_charge, 20.0)
        self.assertAlmostEqual(
            buy.total,
            buy.statutory_and_broker_fees + buy.execution_drag,
        )
        self.assertGreater(sell.total, buy.total)

    def test_liquidity_policy_rejects_illiquid_targets(self) -> None:
        panel = panel_fixture()
        panel["volume"] = 1
        schedule = IndianDeliveryCostSchedule(minimum_daily_traded_value=1_000_000)
        result = PortfolioEventBacktester(schedule).run(
            StrategyRegistry.create("cross_sectional_momentum"), ResearchDataset("TEST", {}, panel),
        )

        self.assertFalse(result.run.orders.empty)
        self.assertTrue((result.run.orders["status"] == "REJECTED").all())
        self.assertTrue(result.run.fills.empty)

    def test_schema_persists_portfolio_and_rca_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "research.duckdb"))
            try:
                tables = {row[0] for row in db.conn.execute("SHOW TABLES").fetchall()}
                columns = {row[1] for row in db.conn.execute("PRAGMA table_info('strategy_correlations')").fetchall()}
            finally:
                db.close()

        self.assertTrue({
            "experiment_jobs", "portfolio_positions", "fill_cost_components",
            "strategy_equity_curve", "promotion_reviews", "walk_forward_trade_attribution",
            "walk_forward_round_trips",
        }.issubset(tables))
        self.assertTrue({"trade_overlap", "regime_correlation_json", "run_id_a", "run_id_b", "symbol_a", "symbol_b"}.issubset(columns))

    def test_portfolio_persistence_and_walk_forward_evidence_are_reproducible(self) -> None:
        source = panel_fixture()
        result = PortfolioEventBacktester().run(
            StrategyRegistry.create("cross_sectional_momentum"), ResearchDataset("TEST", {}, source),
        )
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "walk-forward.duckdb"))
            try:
                for symbol, bars in source.groupby("symbol"):
                    db.upsert_candles(
                        bars.drop(columns=["symbol", "exchange", "timeframe", "benchmark_close", "sector"]),
                        symbol, symbol, "NSE", "1d",
                    )
                db.log_portfolio_result(result)
                rerun = PortfolioEventBacktester().run(
                    StrategyRegistry.create("cross_sectional_momentum"),
                    ResearchDataset("TEST", {}, source),
                )
                db.log_portfolio_result(rerun)
                persisted_orders = db.conn.execute(
                    "SELECT COUNT(*) FROM strategy_orders WHERE run_id = ?",
                    [result.run.run_id],
                ).fetchone()[0]
                fold_ids = WalkForwardEvaluator(db).evaluate(
                    result.run.run_id,
                    ExperimentSpec(
                        strategy_name="cross_sectional_momentum",
                        universe=sorted(source["symbol"].unique()),
                        timeframe="1d",
                        mode="event-driven",
                        benchmark_symbol=None,
                        universe_snapshot_id="CONFIGURED_UNIVERSE",
                        require_authoritative_certification=False,
                    ),
                    train_size=200,
                    test_size=40,
                )
                evidence = db.conn.execute(
                    "SELECT COUNT(*) FROM strategy_equity_curve WHERE run_id = ? AND evidence_level = 'OUT_OF_SAMPLE'",
                    [result.run.run_id],
                ).fetchone()[0]
                metrics = db.conn.execute(
                    "SELECT COUNT(*) FROM walk_forward_metrics WHERE run_id = ?",
                    [result.run.run_id],
                ).fetchone()[0]
                selected = db.conn.execute(
                    "SELECT selected_parameters_json, candidate_count FROM walk_forward_folds WHERE run_id = ? ORDER BY fold_id LIMIT 1",
                    [result.run.run_id],
                ).fetchone()
                oos_attribution = db.conn.execute(
                    "SELECT COUNT(*) FROM walk_forward_trade_attribution WHERE run_id = ?",
                    [result.run.run_id],
                ).fetchone()[0]
                review = PromotionEngine(db).review(result.run.run_id)
            finally:
                db.close()

        self.assertGreaterEqual(len(fold_ids), 1)
        self.assertEqual(persisted_orders, len(rerun.run.orders))
        self.assertGreater(evidence, 0)
        self.assertGreater(metrics, 0)
        self.assertIsNotNone(selected)
        self.assertGreater(selected[1], 1)
        self.assertGreater(oos_attribution, 0)
        self.assertEqual(review["stage"], "RESEARCH_ONLY")

    def test_completed_curve_slicing_cannot_be_recorded_as_oos(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "legacy-walk-forward.duckdb"))
            try:
                with self.assertRaisesRegex(RuntimeError, "not walk-forward validation"):
                    WalkForwardRecorder(db).record(SimpleNamespace())
            finally:
                db.close()

    def test_single_asset_walk_forward_persists_replaceable_oos_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "single-wf.duckdb"))
            try:
                periods = 180
                close = 100 + 8 * np.sin(np.arange(periods) / 5)
                bars = pd.DataFrame({
                    "timestamp": pd.date_range("2025-01-01", periods=periods, freq="B", tz=IST),
                    "open": close, "high": close + 1, "low": close - 1, "close": close,
                    "volume": [100_000] * periods,
                })
                db.upsert_candles(bars, "TEST-EQ", "1", "NSE", "1d")
                outcome = StrategyPipeline(db, require_authoritative_certification=False).run(
                    strategy_name="trend_following", symbol="TEST-EQ", timeframe="1d",
                    mode="event-driven",
                )
                spec = ExperimentSpec(
                    strategy_name="trend_following", universe=["TEST-EQ"], timeframe="1d",
                    mode="event-driven", benchmark_symbol=None,
                )
                evaluator = WalkForwardEvaluator(db)
                evaluator.evaluate(outcome["result"].run_id, spec, train_size=80, test_size=40)
                first_count = db.conn.execute(
                    "SELECT COUNT(*) FROM walk_forward_trade_attribution WHERE run_id = ?",
                    [outcome["result"].run_id],
                ).fetchone()[0]
                evaluator.evaluate(outcome["result"].run_id, spec, train_size=80, test_size=40)
                second_count = db.conn.execute(
                    "SELECT COUNT(*) FROM walk_forward_trade_attribution WHERE run_id = ?",
                    [outcome["result"].run_id],
                ).fetchone()[0]
            finally:
                db.close()

        self.assertGreater(first_count, 0)
        self.assertEqual(second_count, first_count)

    def test_rca_clusters_correlated_strategies_and_counts_effective_bets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "rca.duckdb"))
            try:
                engine = RCAEngine(db)
                matrix = pd.DataFrame(
                    [[1.0, 0.9, 0.0], [0.9, 1.0, 0.0], [0.0, 0.0, 1.0]],
                    index=["A", "B", "C"], columns=["A", "B", "C"],
                )
                clusters = engine._clusters(matrix)
                effective = engine._effective_bets(matrix)
            finally:
                db.close()

        self.assertEqual(clusters["A"], clusters["B"])
        self.assertNotEqual(clusters["A"], clusters["C"])
        self.assertGreater(effective, 1.0)
        self.assertLess(effective, 3.0)

    def test_rca_refuses_to_substitute_in_sample_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "strict-rca.duckdb"))
            try:
                curve = pd.DataFrame({
                    "timestamp": pd.date_range("2026-01-01", periods=2, tz="UTC"),
                    "equity": [100.0, 101.0], "gross_return": [0.0, 0.01],
                    "net_return": [0.0, 0.01], "drawdown": [0.0, 0.0], "position": [0.0, 1.0],
                })
                db.log_equity_curve("run-a", curve)
                with self.assertRaisesRegex(ValueError, "No OUT_OF_SAMPLE"):
                    RCAEngine(db).analyze(["run-a"])
            finally:
                db.close()

    def test_rca_summary_uses_only_walk_forward_metrics_and_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "oos-rca.duckdb"))
            try:
                curve = pd.DataFrame({
                    "timestamp": pd.date_range("2026-01-01", periods=2, tz="UTC"),
                    "equity": [100.0, 101.0], "gross_return": [0.0, 0.01],
                    "net_return": [0.0, 0.01], "drawdown": [0.0, 0.0], "position": [0.2, 0.2],
                })
                db.log_equity_curve("run-a", curve, evidence_level="OUT_OF_SAMPLE", fold_id="wf-001")
                db._replace_rows("walk_forward_metrics", [{
                    "run_id": "run-a", "fold_id": "wf-001", "train_end": pd.Timestamp("2025-12-31", tz="UTC"),
                    "test_start": pd.Timestamp("2026-01-01", tz="UTC"),
                    "test_end": pd.Timestamp("2026-01-02", tz="UTC"),
                    "metric_name": "sharpe", "metric_value": 2.0,
                }])
                db._replace_rows("walk_forward_trade_attribution", [{
                    "run_id": "run-a", "fold_id": "wf-001", "timestamp": pd.Timestamp("2026-01-02", tz="UTC"),
                    "symbol": "AAA", "side": "SELL", "reason": "rank_removal",
                    "realized_pnl": 10.0, "cost": 1.0, "target_weight": 0.0,
                    "quantity": 1.0, "gross_pnl": 11.0, "holding_period_days": 1.0,
                    "exit_classification": "RANK_REMOVAL",
                }])
                summary = RCAEngine(db).analyze(["run-a"]).strategy_summary.iloc[0]
            finally:
                db.close()

        self.assertEqual(summary["sharpe"], 2.0)
        self.assertEqual(summary["symbols_contributing"], 1)
        self.assertEqual(summary["realized_pnl"], 10.0)

    def test_equity_store_preserves_in_sample_and_oos_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "evidence.duckdb"))
            try:
                curve = pd.DataFrame({
                    "timestamp": [pd.Timestamp("2026-01-01", tz="UTC")],
                    "equity": [100.0], "gross_return": [0.0], "net_return": [0.0],
                    "drawdown": [0.0], "position": [0.0],
                })
                db.log_equity_curve("run-a", curve)
                db.log_equity_curve("run-a", curve, evidence_level="OUT_OF_SAMPLE", fold_id="wf-001")
                count = db.conn.execute(
                    "SELECT COUNT(*) FROM strategy_equity_curve WHERE run_id = 'run-a'"
                ).fetchone()[0]
            finally:
                db.close()
        self.assertEqual(count, 2)

    def test_promotion_uses_run_id_correlation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "promotion.duckdb"))
            try:
                metrics = BacktestMetrics(
                    total_return=0.2, cagr=0.2, volatility=0.1, sharpe=1.0, sortino=1.2,
                    calmar=2.0, max_drawdown=-0.03, max_drawdown_duration=5, var_95=-0.01,
                    cvar_95=-0.015, monte_carlo_sharpe_prob=0.99,
                    win_rate=0.6, profit_factor=1.5, turnover=1.0, exposure=0.2,
                    average_trade=10.0, trades=30, fees=1.0, slippage=1.0,
                )
                db.log_strategy_run({
                    "run_id": "run-a", "strategy_name": "momentum", "asset_class": "INDIA_EQUITY",
                    "symbol": "PORTFOLIO", "timeframe": "1d", "mode": "event-driven",
                    "parameters_json": "{}", "data_hash": "hash", "status": "COMPLETED",
                    "started_at": datetime.now(tz=IST), "finished_at": datetime.now(tz=IST), "notes": None,
                }, metrics)
                curve = pd.DataFrame({
                    "timestamp": [pd.Timestamp("2026-01-01", tz="UTC")], "equity": [100.0],
                    "gross_return": [0.0], "net_return": [0.0], "drawdown": [0.0], "position": [0.2],
                })
                db.log_equity_curve("run-a", curve, evidence_level="OUT_OF_SAMPLE", fold_id="wf-001")
                db._replace_rows("promotion_reviews", [{
                    "review_id": "promoted-b", "strategy_name": "other", "run_id": "run-b",
                    "stage": "PAPER_ACTIVE", "decision": "PASS", "score": 1.0,
                    "reasons_json": "[]", "human_approved": True,
                    "reviewed_at": datetime.now(tz=IST),
                }])
                db._replace_rows("strategy_correlations", [{
                    "analysis_id": "analysis", "strategy_a": "display-a", "strategy_b": "display-b",
                    "run_id_a": "run-a", "run_id_b": "run-b", "return_correlation": 0.95,
                    "evidence_level": "OUT_OF_SAMPLE",
                }])
                review = PromotionEngine(db).review("run-a")
                db.conn.execute("DELETE FROM strategy_correlations")
                missing_review = PromotionEngine(db).review("run-a")
            finally:
                db.close()
        self.assertIn("independent", review["reasons_json"])
        self.assertIn("correlation_evidence", missing_review["reasons_json"])

    def test_portfolio_freezes_stale_held_position_without_contaminating_other_symbols(self) -> None:
        class FixedTarget:
            name = "fixed_target"
            metadata = StrategyMetadata(
                "fixed_target", "1.0.0", "TEST", StrategyScope.CROSS_SECTIONAL,
                ("close",), 1, "DAILY", False,
            )
            parameters = {}

            def validate(self) -> None:
                return None

            def generate_signals(self, panel: pd.DataFrame) -> pd.DataFrame:
                first = panel["timestamp"].min()
                return pd.DataFrame({
                    "timestamp": [first], "symbol": ["AAA"], "target_weight": [0.05],
                    "signal": ["BUY"], "reason": ["test"], "score": [1.0], "rank": [1],
                    "feature_snapshot": ["{}"],
                })

        dates = pd.date_range("2026-01-01", periods=3, freq="B", tz="UTC")
        panel = pd.DataFrame({
            "timestamp": dates[:2], "symbol": "AAA", "open": [100.0, 101.0],
            "high": [101.0, 102.0], "low": [99.0, 100.0], "close": [100.5, 101.5],
            "volume": [100_000, 100_000], "sector": "TEST",
        })
        panel = pd.concat([panel, pd.DataFrame({
            "timestamp": dates, "symbol": "BBB", "open": 100.0, "high": 101.0,
            "low": 99.0, "close": 100.5, "volume": 100_000, "sector": "TEST",
        })], ignore_index=True)
        result = PortfolioEventBacktester().run(FixedTarget(), ResearchDataset("TEST", {}, panel))

        final = result.positions[
            (result.positions["timestamp"] == dates[-1]) & (result.positions["symbol"] == "AAA")
        ]
        self.assertEqual(len(final), 1)
        self.assertEqual(float(final.iloc[0]["quantity"]), float(
            result.positions[result.positions["symbol"] == "AAA"].iloc[-2]["quantity"]
        ))

    def test_ingestion_loads_only_eligible_snapshot_members(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "universe.duckdb"))
            try:
                db._replace_rows("universe_snapshots", [{
                    "snapshot_id": "TEST_UNIVERSE", "name": "Test Universe",
                    "source_url": "https://example.test/universe.csv",
                    "effective_date": date(2026, 1, 1), "content_hash": "test-hash",
                    "survivorship_bias": True,
                }])
                db._replace_rows("universe_snapshot_members", [
                    {
                        "snapshot_id": "TEST_UNIVERSE", "symbol": "AAA", "provider_symbol": "AAA-EQ",
                        "provider_token": "101", "company_name": "AAA Ltd", "sector": "Industrials",
                        "exchange": "NSE", "active_from": date(2026, 1, 1), "active_to": None,
                        "liquidity_eligible": True, "data_eligible": True, "paper_eligible": True,
                    },
                    {
                        "snapshot_id": "TEST_UNIVERSE", "symbol": "BBB", "provider_symbol": "BBB-EQ",
                        "provider_token": None, "company_name": "BBB Ltd", "sector": "Industrials",
                        "exchange": "NSE", "active_from": date(2026, 1, 1), "active_to": None,
                        "liquidity_eligible": True, "data_eligible": True, "paper_eligible": False,
                    },
                ])

                symbols = load_universe_snapshot_symbols(db, "TEST_UNIVERSE")
            finally:
                db.close()

        self.assertEqual(symbols, [{
            "symbol": "AAA-EQ", "token": "101", "exchange": "NSE", "instrument_type": "EQUITY",
            "timeframes": ["1d"],
        }])

    def test_ingestion_rejects_unknown_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "missing-universe.duckdb"))
            try:
                with self.assertRaisesRegex(RuntimeError, "Universe snapshot not found"):
                    load_universe_snapshot_symbols(db, "MISSING")
            finally:
                db.close()

    def test_synchronized_dataset_requires_requested_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "benchmark.duckdb"))
            try:
                bars = panel_fixture(periods=30, symbols=1).drop(
                    columns=["symbol", "exchange", "timeframe", "benchmark_close", "sector"],
                )
                db.upsert_candles(bars, "STOCK0", "101", "NSE", "1d")
                with self.assertRaisesRegex(ValueError, "Benchmark NIFTY"):
                    SynchronizedPanelBuilder(db).build(["STOCK0"], "1d", benchmark_symbol="NIFTY")
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
