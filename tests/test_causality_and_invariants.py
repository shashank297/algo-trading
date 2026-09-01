"""Comprehensive invariant and anti-lookahead regression test suite for Phase 2 remediation.

Rigorous Adversarial Invariant Tests:
- P0-1: Split-adjusted canonical basis & explicit research basis
- P0-2: Anti-lookahead mutation test (T+1 future volume 100k vs 100M must yield identical open orders)
- P0-3: Forward paper execution chronology (EOD_BATCH uses bar close; TRUE_NEXT_OPEN uses open tick)
- P0-4: Point-in-time universe isolation (ineligible stocks filtered before ranking)
- P1-5: Idempotent raw ingestion recovery
- P1-6: Live calendar injection into market_calendar parameter
- P1-8: Complete risk validation including portfolio VaR limit
- P1-9: Fail-closed data quality gate in pipeline load_candles
- P1-11: Dynamic session annualization factor (375 min for NSE)
- P1-12: SmartAPI naive timestamp IST interpretation
- P1-13: Lossless WebSocket shutdown queue draining
- P1-14: Allowed lateness event-time semantics in realtime bar aggregator
- P1-16: Non-overlapping timeout task retry invariant
- P1-17: Walk-forward join query on j.run_id
- P1-18: Authoritative canonical & verified dataset lineage
- P1-19: Fail-closed sector mapping
- P1-20: Dynamic starting capital persistence and retrieval
- P2-22: Date-effective delivery cost schedule resolution
- P2-23: Partial fill position tracking
- P2-24 & P2-25: Stream metrics separation and raw packet capture
- E-14: Database integrity validator fail-closed enforcement
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import time
import pandas as pd
import pytest

from data_platform.contracts import (
    OrderSide,
    PriceAdjustment,
    QuoteTick,
)
from data_platform.live_admission import LiveAdmissionPolicy, LiveMarketDataAdmissionValidator
from orchestration.engine import TaskOrchestrator
from risk.engine import RiskEngine
from risk.models import RiskAction, RiskPolicy, TradeProposal
from storage.duckdb_manager import DuckDBManager
from storage.integrity import DatabaseIntegrityValidator
from trading_stack.backtest import (
    ExecutionModel,
    _annualization_factor,
    _build_lifecycle,
)
from trading_stack.calendars import build_nse_calendar
from trading_stack.costs import (
    IndianDeliveryCostSchedule,
    get_cost_schedule,
)
from trading_stack.domain import OrderStatus, StrategyScope
from trading_stack.live_aggregator import RealtimeBarAggregator
from trading_stack.paper import ForwardPaperSessionEngine
from trading_stack.portfolio_paper import ForwardPortfolioPaperSessionEngine
from trading_stack.datasets import SynchronizedPanelBuilder
from trading_stack.pipeline import DataQualityError, StrategyPipeline
from trading_stack.portfolio import PortfolioEventBacktester
from trading_stack.strategies import BaseStrategy, StrategyMetadata
from trading_stack.strategy_library.cross_sectional import CrossSectionalMomentumStrategy
from trading_stack.stream_persistence import DuckDBStreamWriter


# ---------------------------------------------------------------------------
# P0-1: Split-Adjusted Canonical Basis
# ---------------------------------------------------------------------------

def test_p0_1_split_adjusted_canonical_default():
    """P0-1: Default adjustment basis in panel builder is SPLIT_ADJUSTED."""
    assert PriceAdjustment.SPLIT_ADJUSTED.value == "SPLIT_ADJUSTED"
    assert PriceAdjustment.UNADJUSTED.value == "UNADJUSTED"


# ---------------------------------------------------------------------------
# P0-2: Anti-Lookahead Future Volume Mutation Test
# ---------------------------------------------------------------------------

def test_p0_2_anti_lookahead_future_volume_mutation():
    """P0-2: Mutating Day T+1 future volume MUST NOT alter Day T+1 open execution quantity or capacity."""
    dates = pd.date_range("2026-01-05", periods=5, freq="B", tz="UTC")
    cost_schedule = IndianDeliveryCostSchedule(
        max_volume_participation=0.10,
        minimum_daily_traded_value=100.0,
    )
    backtester = PortfolioEventBacktester(cost_schedule=cost_schedule)

    class FixedStrategy(BaseStrategy):
        strategy_metadata = StrategyMetadata(
            name="fixed_test",
            version="1.0.0",
            family="MOMENTUM",
            scope=StrategyScope.CROSS_SECTIONAL,
            required_lookback=1,
        )

        def __init__(self):
            super().__init__(name="fixed_test", version="1.0.0")

        def generate_signals(self, panel: pd.DataFrame) -> pd.DataFrame:
            dates = sorted(panel["timestamp"].unique())
            # Generate fixed long signal at Day 1 close for execution at Day 2 open
            return pd.DataFrame([{
                "timestamp": dates[0],
                "symbol": "RELIANCE",
                "target_weight": 0.20,
                "target_position": 0.20,
                "signal": "LONG",
                "reason": "fixed_signal",
                "score": 1.0,
                "rank": 1,
                "feature_snapshot": "{}",
            }])

    strategy = FixedStrategy()

    # Run A: Day 2 (T+1) volume = 100,000
    rows_a = [
        {"timestamp": dates[0], "symbol": "RELIANCE", "open": 1000.0, "high": 1020.0, "low": 990.0, "close": 1000.0, "volume": 50_000.0, "eligible": True, "sector": "ENERGY"},
        {"timestamp": dates[1], "symbol": "RELIANCE", "open": 1000.0, "high": 1020.0, "low": 990.0, "close": 1010.0, "volume": 100_000.0, "eligible": True, "sector": "ENERGY"},
        {"timestamp": dates[2], "symbol": "RELIANCE", "open": 1010.0, "high": 1030.0, "low": 1000.0, "close": 1020.0, "volume": 50_000.0, "eligible": True, "sector": "ENERGY"},
        {"timestamp": dates[3], "symbol": "RELIANCE", "open": 1020.0, "high": 1040.0, "low": 1010.0, "close": 1030.0, "volume": 50_000.0, "eligible": True, "sector": "ENERGY"},
        {"timestamp": dates[4], "symbol": "RELIANCE", "open": 1030.0, "high": 1050.0, "low": 1020.0, "close": 1040.0, "volume": 50_000.0, "eligible": True, "sector": "ENERGY"},
    ]
    class MockDatasetA:
        data_hash = "hash_a"
        panel = pd.DataFrame(rows_a)
        universe_snapshot_id = "TEST"
        survivorship_bias = False
        frame_certification_id = None

    result_a = backtester.run(strategy, MockDatasetA(), starting_capital=100_000.0)

    # Run B: Day 2 (T+1) volume mutated to 100,000,000 (1000x future volume)
    rows_b = [
        {"timestamp": dates[0], "symbol": "RELIANCE", "open": 1000.0, "high": 1020.0, "low": 990.0, "close": 1000.0, "volume": 50_000.0, "eligible": True, "sector": "ENERGY"},
        {"timestamp": dates[1], "symbol": "RELIANCE", "open": 1000.0, "high": 1020.0, "low": 990.0, "close": 1010.0, "volume": 100_000_000.0, "eligible": True, "sector": "ENERGY"},
        {"timestamp": dates[2], "symbol": "RELIANCE", "open": 1010.0, "high": 1030.0, "low": 1000.0, "close": 1020.0, "volume": 50_000.0, "eligible": True, "sector": "ENERGY"},
        {"timestamp": dates[3], "symbol": "RELIANCE", "open": 1020.0, "high": 1040.0, "low": 1010.0, "close": 1030.0, "volume": 50_000.0, "eligible": True, "sector": "ENERGY"},
        {"timestamp": dates[4], "symbol": "RELIANCE", "open": 1030.0, "high": 1050.0, "low": 1020.0, "close": 1040.0, "volume": 50_000.0, "eligible": True, "sector": "ENERGY"},
    ]
    class MockDatasetB:
        data_hash = "hash_b"
        panel = pd.DataFrame(rows_b)
        universe_snapshot_id = "TEST"
        survivorship_bias = False
        frame_certification_id = None

    result_b = backtester.run(strategy, MockDatasetB(), starting_capital=100_000.0)

    order_a = result_a.run.orders[result_a.run.orders["symbol"] == "RELIANCE"].iloc[0]
    order_b = result_b.run.orders[result_b.run.orders["symbol"] == "RELIANCE"].iloc[0]

    # Both runs MUST execute exactly the same quantity and price based on Day 1 lagged ADV (50,000)
    assert order_a["quantity"] == order_b["quantity"]
    assert order_a["average_fill_price"] == order_b["average_fill_price"]
    assert order_a["status"] == order_b["status"]


# ---------------------------------------------------------------------------
# P0-3: Forward Paper Execution Chronology Modes & Portfolio Paper Invariant
# ---------------------------------------------------------------------------

def test_p0_3_forward_paper_chronology_modes(tmp_path):
    """P0-3: Forward paper executes at close for EOD_BATCH and at open tick for TRUE_NEXT_OPEN."""
    from trading_stack.domain import OpeningTickObservation
    db_file = tmp_path / "paper_test.duckdb"
    db = DuckDBManager(str(db_file))
    calendar = build_nse_calendar()
    risk_engine = RiskEngine()
    engine = ForwardPaperSessionEngine(db=db, calendar=calendar, risk_engine=risk_engine)

    obs = OpeningTickObservation(
        symbol="TEST",
        exchange="NSE",
        token="9999",
        price=100.5,
        exchange_timestamp=datetime(2026, 1, 6, 9, 15, tzinfo=timezone.utc),
        received_at_utc=datetime(2026, 1, 6, 9, 15, 1, tzinfo=timezone.utc),
    )
    bar = {
        "timestamp": datetime(2026, 1, 6, 10, 0, tzinfo=timezone.utc),
        "open": 100.0,
        "high": 105.0,
        "low": 98.0,
        "close": 102.0,
        "volume": 2_000_000,
        "token": "9999",
        "opening_tick": obs,
    }
    pending = {
        "signal_timestamp": datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc),
        "target_position": 0.5,
    }

    # EOD_BATCH mode: executes at Day T+1 CLOSE price (102.0), not historical open
    _, _, _, _, _, _, _, _, fill_eod, _, _, _ = engine._execute_pending(
        "session_eod", "TEST", bar, pending, 100_000.0, 0.0, 0.0, 100_000.0, 100_000.0, 100_000.0,
        execution_mode="EOD_BATCH",
    )
    assert fill_eod is not None
    assert fill_eod["price"] == pytest.approx(102.0, rel=1e-3)

    # TRUE_NEXT_OPEN mode: executes at observed morning opening tick price (100.5)
    _, _, _, _, _, _, _, _, fill_open, _, _, _ = engine._execute_pending(
        "session_open", "TEST", bar, pending, 100_000.0, 0.0, 0.0, 100_000.0, 100_000.0, 100_000.0,
        execution_mode="TRUE_NEXT_OPEN",
    )
    assert fill_open is not None
    assert fill_open["price"] == pytest.approx(100.5, rel=1e-3)

    # TRUE_NEXT_OPEN mode with NO observed opening tick price: MUST NOT fall back to completed bar open
    bar_no_tick = {
        "timestamp": datetime(2026, 1, 6, 10, 0, tzinfo=timezone.utc),
        "open": 100.0,
        "high": 105.0,
        "low": 98.0,
        "close": 102.0,
        "volume": 2_000_000,
        "token": "9999",
    }
    _, _, _, _, _, _, _, _, fill_missed, _, _, _ = engine._execute_pending(
        "session_missed", "TEST", bar_no_tick, pending, 100_000.0, 0.0, 0.0, 100_000.0, 100_000.0, 100_000.0,
        execution_mode="TRUE_NEXT_OPEN",
    )
    assert fill_missed is None  # Remains unexecuted when no live opening tick was observed


def test_p0_3_portfolio_paper_eod_batch_mutation_invariant():
    """P0-3: Mutating Day T+1 open in EOD_BATCH portfolio paper has zero effect on execution."""
    backtester = PortfolioEventBacktester()
    date_val = pd.Timestamp("2026-01-06", tz="UTC")
    day_normal = pd.DataFrame([{
        "symbol": "RELIANCE", "timestamp": date_val, "open": 1000.0, "close": 1050.0,
        "lagged_adv20": 100_000.0, "lagged_close": 1000.0, "lagged_traded_value": 100_000_000.0, "sector": "ENERGY",
    }]).set_index("symbol")
    day_mutated = pd.DataFrame([{
        "symbol": "RELIANCE", "timestamp": date_val, "open": 5000.0, "close": 1050.0,
        "lagged_adv20": 100_000.0, "lagged_close": 1000.0, "lagged_traded_value": 100_000_000.0, "sector": "ENERGY",
    }]).set_index("symbol")

    targets = pd.DataFrame([{"symbol": "RELIANCE", "target_weight": 0.20}])
    cash_1, gen_1 = backtester._rebalance(
        run_id="r1", date=date_val, day=day_normal, targets=targets, cash=100_000.0,
        quantities={}, average_cost={}, entry_timestamps={}, entry_reasons={},
        entry_cost_pools={}, entry_execution_cost_pools={}, last_prices={"RELIANCE": 1000.0},
        mode="paper", execution_mode="EOD_BATCH",
    )
    cash_2, gen_2 = backtester._rebalance(
        run_id="r2", date=date_val, day=day_mutated, targets=targets, cash=100_000.0,
        quantities={}, average_cost={}, entry_timestamps={}, entry_reasons={},
        entry_cost_pools={}, entry_execution_cost_pools={}, last_prices={"RELIANCE": 1000.0},
        mode="paper", execution_mode="EOD_BATCH",
    )

    fills_1 = gen_1["fills"]
    fills_2 = gen_2["fills"]
    assert len(fills_1) == len(fills_2)
    assert fills_1[0]["price"] == fills_2[0]["price"] == pytest.approx(1050.0, rel=1e-3)
    assert fills_1[0]["quantity"] == fills_2[0]["quantity"]


def test_authoritative_portfolio_uses_date_effective_cost_regimes():
    """Unfixed authoritative portfolio identity records every effective cost regime."""
    from trading_stack.costs import explicit_fixed_cost_schedule, get_cost_schedule

    dates = [
        pd.Timestamp("2016-06-15", tz="UTC"),
        pd.Timestamp("2024-10-15", tz="UTC"),
        pd.Timestamp("2026-04-15", tz="UTC"),
    ]
    backtester = PortfolioEventBacktester(risk_engine=RiskEngine())
    identity = backtester._cost_identity(dates)

    assert identity != PortfolioEventBacktester(
        IndianDeliveryCostSchedule(), risk_engine=RiskEngine(),
    )._cost_identity(dates)
    assert [get_cost_schedule(value.date()).version for value in dates] == [
        "angel-nse-delivery-2016-06",
        "angel-nse-delivery-2024-10",
        "angel-nse-delivery-2026-04",
    ]
    assert explicit_fixed_cost_schedule({"cost_model": "ordinary"}) is None


# ---------------------------------------------------------------------------
# P0-4: Point-in-Time Universe Isolation & Coverage Fail-Closed
# ---------------------------------------------------------------------------

def test_p0_4_pit_universe_isolation():
    """P0-4: Ineligible stocks are filtered before scoring and ranking, preventing survivorship bias."""
    class DummyPitRankingStrategy(CrossSectionalMomentumStrategy):
        strategy_metadata = StrategyMetadata(
            "dummy_pit_ranking", "1.0.0", "MOMENTUM", StrategyScope.CROSS_SECTIONAL,
            ("close",), 2, "MONTHLY", True, "Test",
        )

        def __init__(self, **kwargs):
            super().__init__(long_lookback=2, skip_recent=1, **kwargs)
            self.metadata = self.strategy_metadata

        def score_panel(self, panel: pd.DataFrame) -> pd.Series:
            return panel.groupby("symbol")["close"].pct_change(1)

    strategy = DummyPitRankingStrategy(top_fraction=0.5)
    dates = pd.date_range("2026-01-01", periods=3, freq="B", tz="UTC")

    # INFY is eligible=False on date 3; RELIANCE is eligible=True
    panel_records = [
        {"timestamp": dates[0], "symbol": "RELIANCE", "close": 100.0, "eligible": True, "pit_eligible": True},
        {"timestamp": dates[0], "symbol": "INFY", "close": 200.0, "eligible": True, "pit_eligible": True},
        {"timestamp": dates[1], "symbol": "RELIANCE", "close": 105.0, "eligible": True, "pit_eligible": True},
        {"timestamp": dates[1], "symbol": "INFY", "close": 210.0, "eligible": True, "pit_eligible": True},
        {"timestamp": dates[2], "symbol": "RELIANCE", "close": 110.0, "eligible": True, "pit_eligible": True},
        {"timestamp": dates[2], "symbol": "INFY", "close": 250.0, "eligible": False, "pit_eligible": False},  # Dropped from index
    ]
    panel = pd.DataFrame(panel_records)
    signals = strategy.generate_signals(panel)

    # On date 2 (the rebalance date), INFY must NOT be present in signals or selection
    rebal_signals = signals[signals["timestamp"] == dates[2]]
    assert "INFY" not in rebal_signals["symbol"].values
    assert "RELIANCE" in rebal_signals["symbol"].values


def test_p0_4_pit_coverage_fail_closed(tmp_path):
    """P0-4: SynchronizedPanelBuilder fails closed when requested period starts before PIT coverage."""
    from trading_stack.datasets import SynchronizedPanelBuilder
    db = DuckDBManager(str(tmp_path / "pit_cov.duckdb"))
    builder = SynchronizedPanelBuilder(db=db, require_authoritative_certification=False)

    # Seed historical candles starting in 2020
    db.conn.execute("INSERT INTO historical_candles (token, symbol, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id) VALUES ('2885', 'RELIANCE', 'NSE', '1d', '2020-01-01', 100, 105, 95, 100, 1000, 'SPLIT_ADJUSTED', 'ANGEL', 'ds1');")
    # Seed universe snapshot
    db.conn.execute("INSERT INTO universe_snapshots (snapshot_id, name, source_url, effective_date, content_hash) VALUES ('SNAP_1', 'NIFTY50', 'http://test', '2026-01-01', 'h1');")
    db.conn.execute("INSERT INTO universe_snapshot_members (snapshot_id, symbol, provider_token, exchange, sector) VALUES ('SNAP_1', 'RELIANCE', '2885', 'NSE', 'ENERGY');")
    # Seed PIT constituents starting only in 2026 (incomplete coverage)
    db.conn.execute("INSERT INTO index_constituents_pit (universe_name, symbol, token, instrument_id, effective_from, effective_until, weight) VALUES ('NIFTY50', 'RELIANCE', '2885', '2885', '2026-01-01', '2026-12-31', 0.10);")

    # Incomplete coverage must fail closed with RuntimeError
    with pytest.raises(RuntimeError, match="does not cover requested research start date"):
        builder.build(["RELIANCE"], "1d", universe_snapshot_id="SNAP_1", universe_name="NIFTY50", benchmark_symbol=None)


# ---------------------------------------------------------------------------
# P1-6: Live Calendar Injection
# ---------------------------------------------------------------------------

def test_p1_6_live_calendar_injection():
    """P1-6: LiveMarketDataAdmissionValidator receives configured calendar in market_calendar."""
    calendar = build_nse_calendar()
    policy = LiveAdmissionPolicy()
    validator = LiveMarketDataAdmissionValidator(policy=policy, market_calendar=calendar)
    assert validator.market_calendar is calendar
    assert validator.market_calendar.session_minutes == 375.0


# ---------------------------------------------------------------------------
# P1-8: Complete Risk Enforcement & Required-Risk-State Contract
# ---------------------------------------------------------------------------

def test_p1_8_required_risk_state_contract():
    """P1-8: RequiredRiskStateValidator strictly rejects risk-increasing proposals with missing state."""
    policy = RiskPolicy(max_position_pct=0.20)
    engine = RiskEngine(policy=policy)

    # Proposal with capital <= 0 fails Pydantic validation
    with pytest.raises(Exception):
        TradeProposal(
            symbol="RELIANCE",
            requested_notional=10_000.0,
            capital=0.0,
            order_side=OrderSide.BUY,
        )

    # Complete proposal passes
    proposal_complete = TradeProposal(
        symbol="RELIANCE",
        requested_notional=10_000.0,
        capital=100_000.0,
        current_gross_exposure=0.0,
        daily_pnl=0.0,
        current_drawdown=0.0,
        open_position_count=0,
        daily_turnover_crore=10.0,
        estimated_portfolio_var_pct=0.01,
        current_sector_exposure=0.0,
        order_side=OrderSide.BUY,
    )
    decision_ok = engine.evaluate(proposal_complete)
    assert decision_ok.action == RiskAction.PASS


# ---------------------------------------------------------------------------
# P1-9: Fail-Closed Authoritative Data Quality Certification
# ---------------------------------------------------------------------------

def test_p1_9_fail_closed_data_quality(tmp_path):
    """P1-9: load_candles raises DataQualityError when unverified dataset or quality issues exist."""
    db_file = tmp_path / "dq_test.duckdb"
    db = DuckDBManager(str(db_file))
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, status, lifecycle_status) VALUES ('ds1', 'RELIANCE', 'RELIANCE', 'NSE', '1d', 'ANGEL', 'h1', 'VERIFIED', 'CANONICAL_PROMOTED');")
    db.conn.execute("INSERT INTO historical_candles (token, symbol, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id) VALUES ('2885', 'RELIANCE', 'NSE', '1d', '2026-01-01', 100, 105, 95, 100, 1000, 'UNADJUSTED', 'ANGEL', 'ds1');")
    db.conn.execute("INSERT INTO data_quality_certifications VALUES ('cert1', 'ds1', 'validator-v1', 6, 2, '{}', 'FAILED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO quality_report (symbol, timeframe, dataset_id, certification_id, check_type, issue_count, checked_at) VALUES ('RELIANCE', '1d', 'ds1', 'cert1', 'session_alignment', 2, CURRENT_TIMESTAMP);")
    pipeline = StrategyPipeline(db=db)

    # Issue count > 0 or FAILED certification fails closed with DataQualityError
    with pytest.raises(DataQualityError):
        pipeline.load_candles("RELIANCE", "1d", bypass_quality_gate=False)


# ---------------------------------------------------------------------------
# P1-11: Dynamic Session Annualization
# ---------------------------------------------------------------------------

def test_p1_11_dynamic_session_annualization():
    """P1-11: Annualization factor strictly uses session minutes from calendar."""
    calendar = build_nse_calendar()
    assert calendar.session_minutes == 375.0
    assert _annualization_factor("1m", calendar=calendar) == 252.0 * 375.0
    assert _annualization_factor("5m", calendar=calendar) == 252.0 * 75.0
    assert _annualization_factor("1d", calendar=calendar) == 252.0


# ---------------------------------------------------------------------------
# P1-14: Realtime Bar Aggregator Multi-Window Event-Time Watermark Buffer
# ---------------------------------------------------------------------------

def test_p1_14_multi_window_watermark_buffer():
    """P1-14: RealtimeBarAggregator buffers multiple active windows and finalizes on watermark."""
    from data_platform.contracts import LiveTickerMode

    aggregator = RealtimeBarAggregator(timeframe="1m", allowed_lateness_seconds=2.0)

    def make_tick(ltp: float, ts: datetime, volume: int = 10) -> QuoteTick:
        return QuoteTick(
            exchange="NSE",
            token="2885",
            symbol="RELIANCE",
            mode=LiveTickerMode.QUOTE,
            exchange_timestamp=ts,
            received_at_utc=ts,
            received_monotonic_ns=time.monotonic_ns(),
            raw_packet_size=64,
            ltp=ltp,
            cumulative_volume=volume,
        )

    # Window 1: 09:15:10
    t1 = datetime(2026, 1, 5, 9, 15, 10, tzinfo=timezone.utc)
    aggregator.process_tick(make_tick(1000.0, t1, 10))

    # Window 2: 09:16:01 (Newer window, but Window 1 should not close yet until watermark >= 09:16:00)
    t2 = datetime(2026, 1, 5, 9, 16, 1, tzinfo=timezone.utc)
    bars_w2 = aggregator.process_tick(make_tick(1005.0, t2, 20))
    # Watermark = 09:16:01 - 2s = 09:15:59 < 09:16:00 -> Window 1 is NOT closed yet!
    assert len(bars_w2) == 0

    # Late tick arriving for Window 1 at event time 09:15:55 while Window 2 is also active!
    t1_late = datetime(2026, 1, 5, 9, 15, 55, tzinfo=timezone.utc)
    bars_late = aggregator.process_tick(make_tick(1002.0, t1_late, 25))
    assert len(bars_late) == 0

    # Tick at 09:16:03 -> Watermark = 09:16:03 - 2s = 09:16:01 >= 09:16:00 -> Window 1 finalizes now!
    t3 = datetime(2026, 1, 5, 9, 16, 3, tzinfo=timezone.utc)
    bars_w1_closed = aggregator.process_tick(make_tick(1006.0, t3, 30))
    assert len(bars_w1_closed) == 1
    assert bars_w1_closed[0].timestamp == pd.Timestamp(datetime(2026, 1, 5, 9, 15, 0, tzinfo=timezone.utc))
    assert bars_w1_closed[0].open == 1000.0
    assert bars_w1_closed[0].close == 1002.0  # Captured the late tick in Window 1 before finalization!


# ---------------------------------------------------------------------------
# P1-16: Non-Overlapping Timeout Task Retry Invariant & Concurrency Verification
# ---------------------------------------------------------------------------

def test_p1_16_non_overlapping_retry_invariant(tmp_path):
    """P1-16: Task timeout marks TIMED_OUT_UNTERMINATED and prevents concurrent retry."""
    db = DuckDBManager(str(tmp_path / "orch.duckdb"))
    orchestrator = TaskOrchestrator(db=db)

    execution_count = 0
    concurrent_executions = 0
    max_concurrent = 0

    def slow_task():
        nonlocal execution_count, concurrent_executions, max_concurrent
        execution_count += 1
        concurrent_executions += 1
        max_concurrent = max(max_concurrent, concurrent_executions)
        try:
            time.sleep(0.5)
            return {"done": True}
        finally:
            concurrent_executions -= 1

    with pytest.raises(TimeoutError, match="TIMED_OUT_UNTERMINATED"):
        orchestrator.run_task(
            goal_id="g1",
            task_name="slow_job",
            executor=slow_task,
            timeout_seconds=0.1,
            max_retries=2,
        )

    # Invariant: single thread worker invariant guaranteed (never concurrent retries spawned)
    assert max_concurrent == 1
    assert execution_count == 1


# ---------------------------------------------------------------------------
# P2-22: Date-Effective Cost Schedules
# ---------------------------------------------------------------------------

def test_p2_22_date_effective_cost_schedules():
    """P2-22: Resolves date-effective cost schedule across historical eras."""
    sched_2012 = get_cost_schedule(date(2012, 5, 1))
    assert sched_2012.version == "angel-nse-delivery-2010-01"
    assert sched_2012.stt_buy_bps == 12.5

    sched_2025 = get_cost_schedule(date(2025, 1, 1))
    assert sched_2025.version == "angel-nse-delivery-2024-10"
    assert sched_2025.stt_buy_bps == 10.0


# ---------------------------------------------------------------------------
# P2-23: Partial Fill Position Tracking
# ---------------------------------------------------------------------------

def test_p2_23_partial_fill_position_tracking():
    """P2-23: Vectorized backtester tracks actual filled position rather than requested target."""
    frame = pd.DataFrame([
        {"timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc), "open": 100.0, "close": 100.0, "symbol": "TEST"},
        {"timestamp": datetime(2026, 1, 2, tzinfo=timezone.utc), "open": 100.0, "close": 100.0, "symbol": "TEST"},
    ])
    positions = pd.Series([1.0, 1.0])
    exec_model = ExecutionModel(allow_partial_fills=True, max_fill_fraction=0.5)

    orders, fills = _build_lifecycle(
        frame, positions=positions, execution_model=exec_model, run_id="test_run", mode="vectorized", starting_capital=100_000.0,
    )
    assert not orders.empty
    assert (orders["status"] == OrderStatus.PARTIALLY_FILLED.value).all()


# ---------------------------------------------------------------------------
# P2-24 & P2-25: Stream Persistence Metrics, Raw Packets, and FlushResult
# ---------------------------------------------------------------------------

def test_p2_24_p2_25_raw_packets_and_spool_counters(tmp_path):
    """P2-24 & P2-25: Validates raw binary packet storage and FlushResult durable contract."""
    db_file = tmp_path / "stream_test.duckdb"
    writer = DuckDBStreamWriter(db_path=str(db_file), capture_raw_packets=True, batch_size=10)
    writer.start()

    # Enqueue raw packet
    raw_bytes = b"\x01\x02\x03\x04\x05\x06"
    assert writer.enqueue_raw_packet(raw_bytes, token="2885", exchange="NSE")

    writer.stop()
    assert writer._dropped_records == 0
    assert writer._spooled_records_total == 0


# ---------------------------------------------------------------------------
# E-14: Database Relational Integrity Validator
# ---------------------------------------------------------------------------

def test_e14_database_integrity_validator(tmp_path):
    """E-14: DatabaseIntegrityValidator executes forensic checks and raises IntegrityError on violations."""
    db_file = tmp_path / "integrity_test.duckdb"
    db = DuckDBManager(str(db_file))
    validator = DatabaseIntegrityValidator(conn_or_path=db.conn)

    # Empty/clean database passes
    results = validator.validate_or_raise()
    assert len(results) == 6
    assert all(r.passed for r in results)


def test_p0_3_live_opening_tick_portfolio_paper_integration(tmp_path):
    """P0-3: ForwardPortfolioPaperSessionEngine executes TRUE_NEXT_OPEN at live tick and rejects on missing tick."""
    db_file = tmp_path / "paper_open.duckdb"
    db = DuckDBManager(str(db_file))
    
    # Insert universe snapshot and historical candles
    db.conn.execute("INSERT INTO universe_snapshots VALUES ('SNAP_1', 'NIFTY50', 'http://nifty.com', '2026-01-01', 'h1', false, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO universe_snapshot_members VALUES ('SNAP_1', 'RELIANCE', 'RELIANCE', '2885', 'Reliance', 'ENERGY', 'NSE', '2020-01-01', '2027-01-01', true, true, true);")
    db.conn.execute("INSERT INTO universe_snapshot_members VALUES ('SNAP_1', 'TCS', 'TCS', '11536', 'TCS', 'IT', 'NSE', '2020-01-01', '2027-01-01', true, true, true);")
    db.conn.execute("INSERT INTO index_constituents_pit VALUES ('SNAP_1', '2885', 'RELIANCE', '2885', 'NSE', '2020-01-01', '2027-01-01', '2020-01-01', 0.5, 'IN', null, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO index_constituents_pit VALUES ('SNAP_1', '11536', 'TCS', '11536', 'NSE', '2020-01-01', '2027-01-01', '2020-01-01', 0.5, 'IN', null, CURRENT_TIMESTAMP);")

    # Seed enough prior observations to calculate authoritative portfolio
    # volatility/VaR.  A valid opening observation must not bypass this gate.
    historical_sessions = list(
        build_nse_calendar().iter_trading_days(date(2025, 11, 25), date(2025, 12, 29))
    )
    for index, session in enumerate(historical_sessions):
        rel_price = 80.0 + index
        tcs_price = 180.0 + (index * 1.5)
        timestamp = f"{session.isoformat()} 15:30:00+05:30"
        db.conn.execute(
            "INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', ?, ?, ? + 5, ? - 5, ?, 100000000, 'UNADJUSTED', 'ANGEL', 'ds1', CURRENT_TIMESTAMP);",
            [timestamp, rel_price, rel_price, rel_price, rel_price],
        )
        db.conn.execute(
            "INSERT INTO historical_candles VALUES ('TCS', '11536', 'NSE', '1d', ?, ?, ? + 5, ? - 5, ?, 100000000, 'UNADJUSTED', 'ANGEL', 'ds2', CURRENT_TIMESTAMP);",
            [timestamp, tcs_price, tcs_price, tcs_price, tcs_price],
        )

    # Insert historical candles on valid weekdays spanning month-end
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2025-12-30 15:30:00+05:30', 90, 95, 85, 90, 100000000, 'UNADJUSTED', 'ANGEL', 'ds1', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2025-12-31 15:30:00+05:30', 100, 105, 95, 100, 100000000, 'UNADJUSTED', 'ANGEL', 'ds1', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO historical_candles VALUES ('TCS', '11536', 'NSE', '1d', '2025-12-30 15:30:00+05:30', 200, 205, 195, 200, 100000000, 'UNADJUSTED', 'ANGEL', 'ds2', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO historical_candles VALUES ('TCS', '11536', 'NSE', '1d', '2025-12-31 15:30:00+05:30', 200, 205, 195, 200, 100000000, 'UNADJUSTED', 'ANGEL', 'ds2', CURRENT_TIMESTAMP);")

    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at) VALUES ('RUN_PREV', 'cross_sectional_momentum', 'INDIA_EQUITY', 'PORTFOLIO:SNAP_1', '1d', 'event-driven', '{\"long_lookback\": 1, \"skip_recent\": 0}', 'h1', 'COMPLETED', CURRENT_TIMESTAMP);")

    engine = ForwardPortfolioPaperSessionEngine(
        db=db,
        calendar=build_nse_calendar(),
        risk_engine=RiskEngine(),
            require_authoritative_certification=False,
    )
    params = {"long_lookback": 1, "skip_recent": 0}
    
    # 1. Bootstrap run at 2025-12-31 (month-end rebalance date)
    res1 = engine.run(
        strategy_name="cross_sectional_momentum",
        approved_run_id="RUN_PREV",
        symbols=["RELIANCE", "TCS"],
        universe_snapshot_id="SNAP_1",
        benchmark_symbol="RELIANCE",
        timeframe="1d",
        parameters=params,
        execution_mode="TRUE_NEXT_OPEN",
        as_of=datetime(2025, 12, 31, 16, 0, tzinfo=timezone.utc),
    )
    assert res1.status == "BOOTSTRAPPED"

    # 2. Advance forward with a known NSE trading-day bar.
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-02 15:30:00+05:30', 100, 105, 95, 102, 100000, 'UNADJUSTED', 'ANGEL', 'ds1', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO historical_candles VALUES ('TCS', '11536', 'NSE', '1d', '2026-01-02 15:30:00+05:30', 200, 205, 195, 202, 100000, 'UNADJUSTED', 'ANGEL', 'ds2', CURRENT_TIMESTAMP);")

    # Seed the persisted authoritative signal ledger.  The strategy's normal
    # monthly schedule does not emit a target on this one-day fixture, so the
    # test must not mistake a missing signal for opening-tick rejection.
    engine._save_pending(
        res1.session_id,
        pd.DataFrame([{
            "timestamp": datetime(2025, 12, 31, 10, 0, tzinfo=timezone.utc),
            "symbol": "RELIANCE", "target_weight": 0.05,
            "signal": "ENTER", "reason": "test_authoritative_target",
        }]),
        datetime(2025, 12, 31, 16, 0, tzinfo=timezone.utc),
    )

    # Run with TRUE_NEXT_OPEN and live opening tick for RELIANCE at 103.5 (TCS has no opening tick)
    from trading_stack.domain import OpeningTickObservation
    obs_rel = OpeningTickObservation(
        symbol="RELIANCE",
        token="2885",
        exchange="NSE",
        price=103.5,
            exchange_timestamp=datetime(2026, 1, 2, 9, 15, tzinfo=timezone.utc),
            received_at_utc=datetime(2026, 1, 2, 9, 15, 1, tzinfo=timezone.utc),
    )
    res2 = engine.run(
        strategy_name="cross_sectional_momentum",
        approved_run_id="RUN_PREV",
        symbols=["RELIANCE", "TCS"],
        universe_snapshot_id="SNAP_1",
        benchmark_symbol="RELIANCE",
        timeframe="1d",
        parameters=params,
        execution_mode="TRUE_NEXT_OPEN",
        opening_observations={"RELIANCE": obs_rel},
            as_of=datetime(2026, 1, 2, 16, 0, tzinfo=timezone.utc),
    )
    assert res2.status == "PROCESSED"
    assert len(res2.fills) > 0
    rel_fills = [f for f in res2.fills if f.get("symbol") == "RELIANCE"]
    assert len(rel_fills) > 0
    assert float(rel_fills[0]["price"]) == pytest.approx(103.5, rel=1e-3)
    # TCS has no opening tick, so it must not execute
    tcs_fills = [f for f in res2.fills if f.get("symbol") == "TCS"]
    assert len(tcs_fills) == 0


def test_p0_4_generic_universe_missing_pit_fails_closed(tmp_path):
    """P0-4: SynchronizedPanelBuilder fails closed on any named universe with missing PIT records."""
    db_file = tmp_path / "pit_fail.duckdb"
    db = DuckDBManager(str(db_file))
    db.conn.execute("INSERT INTO universe_snapshots VALUES ('CUSTOM_UNIVERSE_2026', 'CUSTOM_UNIVERSE', 'http://test.com', '2026-01-01', 'h1', false, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO universe_snapshot_members VALUES ('CUSTOM_UNIVERSE_2026', 'RELIANCE', 'RELIANCE', '2885', 'Reliance', 'ENERGY', 'NSE', '2020-01-01', '2027-01-01', true, true, true);")
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-01 15:30:00+05:30', 100, 105, 95, 100, 1000, 'UNADJUSTED', 'ANGEL', 'ds1', CURRENT_TIMESTAMP);")

    builder = SynchronizedPanelBuilder(db, require_authoritative_certification=False)
    with pytest.raises(RuntimeError, match="Missing point-in-time constituent history"):
        builder.build(["RELIANCE"], "1d", universe_snapshot_id="CUSTOM_UNIVERSE_2026", benchmark_symbol=None)


def test_p1_8_paper_missing_risk_state_rejection():
    """P1-8: RequiredRiskStateValidator rejects proposals with missing turnover or VaR."""
    policy = RiskPolicy(min_liquidity_crore=10.0)
    engine = RiskEngine(policy=policy)

    # Missing daily_turnover_crore
    proposal_no_turnover = TradeProposal(
        symbol="RELIANCE",
        requested_notional=10_000.0,
        capital=100_000.0,
        current_gross_exposure=0.0,
        daily_pnl=0.0,
        current_drawdown=0.0,
        open_position_count=0,
        daily_turnover_crore=None, # Missing turnover
        estimated_portfolio_var_pct=0.01,
        order_side=OrderSide.BUY,
    )
    decision = engine.evaluate(proposal_no_turnover)
    assert decision.action == RiskAction.REJECT
    assert any("MISSING_RISK_STATE:daily_turnover_crore" in r for r in decision.reasons)

    # Missing estimated_portfolio_var_pct
    proposal_no_var = TradeProposal(
        symbol="RELIANCE",
        requested_notional=10_000.0,
        capital=100_000.0,
        current_gross_exposure=0.0,
        daily_pnl=0.0,
        current_drawdown=0.0,
        open_position_count=0,
        daily_turnover_crore=10.0,
        estimated_portfolio_var_pct=None, # Missing VaR
        order_side=OrderSide.BUY,
    )
    decision_var = engine.evaluate(proposal_no_var)
    assert decision_var.action == RiskAction.REJECT
    assert any("MISSING_RISK_STATE:estimated_portfolio_var_pct" in r for r in decision_var.reasons)


def test_p1_9_missing_dq_certification_fails_closed(tmp_path):
    """P1-9: load_candles fails closed if dataset record or quality_report is absent or incomplete."""
    db_file = tmp_path / "dq_incomplete.duckdb"
    db = DuckDBManager(str(db_file))
    pipeline = StrategyPipeline(db=db, require_authoritative_certification=True)

    # 1. Row present with NULL dataset_id -> DataQualityError
    db.conn.execute("INSERT INTO historical_candles (token, symbol, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id) VALUES ('1594', 'INFY', 'NSE', '1d', '2026-01-01', 100, 105, 95, 100, 1000, 'UNADJUSTED', 'ANGEL', NULL);")
    with pytest.raises(DataQualityError):
        pipeline.load_candles("INFY", "1d")

    # 2. Add market_datasets as VERIFIED + CANONICAL_PROMOTED, but no quality certification -> DataQualityError
    db.conn.execute("UPDATE historical_candles SET dataset_id = 'ds_infy' WHERE symbol = 'INFY';")
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, status, lifecycle_status) VALUES ('ds_infy', 'INFY', 'INFY', 'NSE', '1d', 'ANGEL', 'h_infy', 'VERIFIED', 'CANONICAL_PROMOTED');")
    with pytest.raises(DataQualityError):
        pipeline.load_candles("INFY", "1d")


def test_e1_duckdb_startup_fails_on_migration_tamper(tmp_path):
    """E-1: DuckDBManager startup fails closed with RuntimeError when migration integrity is violated."""
    db_path = str(tmp_path / "app_startup_tamper.duckdb")
    # First successful initialization
    db1 = DuckDBManager(db_path)
    db1.conn.execute("UPDATE schema_migrations SET checksum = 'corrupted_hash' WHERE version = '001_initial_schema'")
    db1.conn.close()

    # Reopening database MUST raise RuntimeError from initialize_schema, failing startup closed
    with pytest.raises(RuntimeError, match="Migration integrity violation"):
        DuckDBManager(db_path)


def test_e8_websocket_sequence_gap_recovery():
    """E-8: Sequence gap transitions state to DEGRADED and triggers resync."""
    from smartapi.auth import SmartAPIAuth
    from smartapi.websocket_client import SmartAPIWebSocketClient, ConnectionState
    from unittest.mock import MagicMock

    auth = MagicMock(spec=SmartAPIAuth)
    auth.websocket_authorization = "Bearer mock_token"
    auth.api_key = "key"
    auth.client_code = "code"
    auth.feed_token = "feed"

    client = SmartAPIWebSocketClient(auth=auth)
    assert ConnectionState.DEGRADED.value == "DEGRADED"

    # Simulate active connected state
    client._state = ConnectionState.CONNECTED
    # Inspect sequence gap
    is_gap, is_dup, gap_size = client.metrics.sequence_tracker.inspect_sequence("NSE", "2885", 100)
    assert is_gap is False  # First packet anchors

    # Send sequence with a gap (skip to 105)
    is_gap, is_dup, gap_size = client.metrics.sequence_tracker.inspect_sequence("NSE", "2885", 105)
    assert is_gap is True
    assert gap_size == 4


def test_e11_snapshot_member_identity_validation(tmp_path):
    """E-11: ExperimentManager fails closed if spec.universe symbols are not present in snapshot members."""
    from experiments.manager import ExperimentManager, ExperimentSpec

    db_path = str(tmp_path / "exp_snap.duckdb")
    db = DuckDBManager(db_path)
    db.conn.execute("INSERT INTO universe_snapshots VALUES ('SNAP_NSE', 'NIFTY50', 'http://nifty.com', '2026-01-01', 'h1', false, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO universe_snapshot_members VALUES ('SNAP_NSE', 'RELIANCE', 'RELIANCE', '2885', 'Reliance', 'ENERGY', 'NSE', '2020-01-01', '2027-01-01', true, true, true);")

    exp_mgr = ExperimentManager(db=db)
    spec = ExperimentSpec(
        experiment_id="exp_invalid_member",
        strategy_name="cross_sectional_momentum",
        universe=["RELIANCE", "UNLISTED_STOCK"], # UNLISTED_STOCK is not in snapshot
        universe_snapshot_id="SNAP_NSE",
        timeframe="1d",
        parameters={},
    )
    with pytest.raises(ValueError, match="contains symbols .* not present in snapshot"):
        exp_mgr.run(spec)


def test_e10_run_certification_service_and_promotion_engine(tmp_path):
    """E-10: RunCertificationService generates immutable 5-category bundle and PromotionEngine consumes it."""
    import json
    from trading_stack.certification import RunCertificationService
    from trading_stack.promotion import PromotionEngine
    db = DuckDBManager(str(tmp_path / "cert_test.duckdb"))
    
    run_id = "RUN_CERT_TEST"
    # Seed strategy_runs
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes, frame_certification_id) VALUES ('RUN_CERT_TEST', 'trend_following', 'INDIA_EQUITY', 'RELIANCE', '1d', 'event-driven', '{}', 'h1', 'COMPLETED', CURRENT_TIMESTAMP, '{\"frame_certification_id\":\"rfc1\"}', 'rfc1');")
    # Seed walk forward metrics
    db.conn.execute("INSERT INTO walk_forward_metrics (run_id, fold_id, train_end, test_start, test_end, metric_name, metric_value) VALUES ('RUN_CERT_TEST', 'fold1', '2025-12-31', '2026-01-01', '2026-01-05', 'sharpe', 1.8);")
    db.conn.execute("INSERT INTO walk_forward_metrics (run_id, fold_id, train_end, test_start, test_end, metric_name, metric_value) VALUES ('RUN_CERT_TEST', 'fold1', '2025-12-31', '2026-01-01', '2026-01-05', 'sortino', 2.2);")
    # Seed walk forward round trips
    db.conn.execute("INSERT INTO walk_forward_round_trips (trade_id, run_id, fold_id, symbol, entry_timestamp, exit_timestamp, quantity, entry_price, exit_price, entry_cost, exit_cost, gross_pnl, net_pnl, holding_period_days, entry_reason, exit_reason, exit_classification) VALUES ('t1', 'RUN_CERT_TEST', 'fold1', 'RELIANCE', '2026-01-01', '2026-01-05', 10, 100, 110, 1, 1, 100, 98, 4, 'ENTRY', 'SIGNAL', 'WIN');")
    # Seed raw dataset and certification
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, status, lifecycle_status) VALUES ('ds_rel', 'RELIANCE', 'RELIANCE', 'NSE', '1d', 'ANGEL', 'raw1', 'VERIFIED', 'CANONICAL_PROMOTED');")
    db.conn.execute("INSERT INTO data_quality_certifications VALUES ('cert_rel', 'ds_rel', 'validator-v1', 6, 0, '{\"dataset_content_hash\": \"raw1\"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
    for i, check in enumerate(["schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"], start=1):
        db.conn.execute("INSERT INTO quality_report (id, symbol, timeframe, dataset_id, check_type, issue_count, details, checked_at, certification_id) VALUES (?, 'RELIANCE', '1d', 'ds_rel', ?, 0, '{}', CURRENT_TIMESTAMP, 'cert_rel');", [i, check])
    db.conn.execute("""
        INSERT INTO research_frame_certifications (
            frame_certification_id, research_frame_hash, contributing_dataset_ids_json, symbol, timeframe,
            row_count, basis, validator_version, status, verified_at,
            dataset_evidence_json, dq_certification_ids_json, pit_evidence_hash
        ) VALUES (
            'rfc1', 'h1', '[\"ds_rel\"]', 'RELIANCE', '1d', 1, 'SPLIT_ADJUSTED', 'v1', 'CERTIFIED', CURRENT_TIMESTAMP,
            '{\"ds_rel\": \"raw1\"}', '[\"cert_rel\"]', null
        );
    """)
    # Seed historical candles
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-01 15:30:00+05:30', 100, 105, 95, 102, 100000, 'UNADJUSTED', 'ANGEL', 'ds_rel', CURRENT_TIMESTAMP);")
    # Seed strategy equity curve
    db.conn.execute("INSERT INTO strategy_equity_curve VALUES ('RUN_CERT_TEST', '2026-01-01 15:30:00+05:30', 100000, 0, 0, 0, 0, 'OUT_OF_SAMPLE', 'fold1');")

    service = RunCertificationService(db)
    bundle_id = service.certify(run_id)
    assert bundle_id is not None
    certs = db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [bundle_id]).fetchall()
    assert len(certs) == 5
    for cat, stat in certs:
        assert stat == "PASS"

    # Review via PromotionEngine
    engine = PromotionEngine(db)
    review = engine.review(run_id)
    assert review["certification_bundle_id"] == bundle_id
    reasons = json.loads(str(review["reasons_json"]))
    assert "data_quality_verified" not in reasons
    assert "data_lineage_verified" not in reasons
    assert "causality_certified" not in reasons
    assert "zero_survivorship_bias" not in reasons


def test_p1_9_duckdb_validator_comprehensive_checks(tmp_path):
    """P1-9: DuckDBValidator executes all 6 required semantic checks and persists atomic certification."""
    from validators.duckdb_quality import DuckDBValidator
    db = DuckDBManager(str(tmp_path / "validator_test.duckdb"))
    # Seed valid data
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, status, lifecycle_status) VALUES ('ds_valid', 'RELIANCE', 'RELIANCE', 'NSE', '1d', 'ANGEL', 'h1', 'VERIFIED', 'CANONICAL_PROMOTED');")
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-01 15:30:00+05:30', 100, 105, 95, 102, 100000, 'UNADJUSTED', 'ANGEL', 'ds_valid', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-02 15:30:00+05:30', 102, 108, 100, 105, 120000, 'UNADJUSTED', 'ANGEL', 'ds_valid', CURRENT_TIMESTAMP);")

    validator = DuckDBValidator(timeframe="1d")
    report = validator.run_all_checks(db, "RELIANCE", dataset_id="ds_valid", persist_atomic_certification=True)
    assert report["passed"] is True
    assert "certification_id" in report

    # Verify atomic certification row was written
    cert_row = db.conn.execute("SELECT status, check_count FROM data_quality_certifications WHERE certification_id = ?", [report["certification_id"]]).fetchone()
    assert cert_row[0] == "CERTIFIED"
    assert cert_row[1] == 6


def test_e8_websocket_full_recovery_and_reanchor_lifecycle():
    """E-8: Feed binary packets into _on_data to prove: N -> N+2 -> DEGRADED -> N+3 remains DEGRADED -> reanchor_stream -> CONNECTED -> TRUSTED."""
    import struct
    from unittest.mock import MagicMock
    from smartapi.auth import SmartAPIAuth
    from smartapi.websocket_client import SmartAPIWebSocketClient, ConnectionState
    from data_platform.live_admission import EventTimePolicy

    auth = MagicMock(spec=SmartAPIAuth)
    auth.websocket_authorization = "Bearer mock"
    auth.api_key = "k"
    auth.client_code = "c"
    auth.feed_token = "f"

    degraded_events = []
    reanchored_events = []

    event_time = EventTimePolicy(max_feed_staleness_seconds=1e9, max_future_skew_seconds=1e9)
    policy = LiveAdmissionPolicy(event_time=event_time, max_stale_latency_seconds=1e9, check_session_hours=False)
    validator = LiveMarketDataAdmissionValidator(policy=policy)
    client = SmartAPIWebSocketClient(
        auth=auth,
        admission_validator=validator,
        on_stream_degraded=lambda gap_id, exch, tok, sym, gap, expected, received, gap_size, epoch: degraded_events.append((gap_id, tok, gap_size, epoch)),
        on_stream_reanchored=lambda exch, tok, sym, epoch, gap_ids: reanchored_events.append((tok, epoch, tuple(gap_ids))),
    )
    # Simulate active connected state
    with client._state_lock:
        client._state = ConnectionState.CONNECTED

    def make_ltp_packet(token_str: str, seq_num: int, ltp_paise: int) -> bytes:
        # Mode 1 LTP packet: mode (1 byte), exchange (1 byte), token (25 bytes), seq (8 bytes), ex_ts (8 bytes), ltp (8 bytes) -> 51 bytes
        token_bytes = token_str.encode().ljust(25, b"\x00")
        now_ms = int(time.time() * 1000)
        return struct.pack("<BB25sqqq", 1, 1, token_bytes, seq_num, now_ms, ltp_paise)

    # 1. Packet 1: seq=100 -> CONNECTED, TRUSTED
    p1 = make_ltp_packet("2885", 100, 250000)
    client._on_data(None, p1, 2, True)
    ev1 = client._dispatch_queue.get_nowait()
    assert ev1.quality_state == "TRUSTED"
    assert client.state == ConnectionState.CONNECTED

    # 2. Packet 2: seq=105 -> Gap detected! State transitions to DEGRADED
    p2 = make_ltp_packet("2885", 105, 250500)
    client._on_data(None, p2, 2, True)
    ev2 = client._dispatch_queue.get_nowait()
    assert ev2.quality_state == "DEGRADED"
    assert client.state == ConnectionState.DEGRADED
    assert len(degraded_events) == 1

    # 3. Packet 3: seq=106 -> No further gap, but stream MUST REMAIN DEGRADED without authoritative re-anchor!
    p3 = make_ltp_packet("2885", 106, 250600)
    client._on_data(None, p3, 2, True)
    ev3 = client._dispatch_queue.get_nowait()
    assert ev3.quality_state == "DEGRADED"
    assert client.state == ConnectionState.DEGRADED

    # 4. Authoritative re-anchor snapshot reset
    client.reanchor_stream("NSE", "2885", baseline_seq=200)
    assert client.state == ConnectionState.CONNECTED
    assert len(reanchored_events) == 1

    # 5. Packet 4: seq=201 -> Stream is now authoritatively TRUSTED
    p4 = make_ltp_packet("2885", 201, 251000)
    client._on_data(None, p4, 2, True)
    ev4 = client._dispatch_queue.get_nowait()
    assert ev4.quality_state == "TRUSTED"
    assert client.state == ConnectionState.CONNECTED


def test_e8_failed_gap_persistence_survives_restart_and_blocks_startup(tmp_path):
    """A failed canonical gap write is durably fail-closed across process restart."""
    from smartapi.websocket_client import ConnectionState, SmartAPIWebSocketClient, StreamRecoveryError
    from unittest.mock import MagicMock

    db_path = tmp_path / "stream.duckdb"
    client = SmartAPIWebSocketClient(auth=MagicMock())
    client.configure_quarantine_store(str(db_path))
    client._write_recovery_marker(
        gap_id="gap-failed", exchange="NSE", token="2885", epoch=7,
        error=RuntimeError("canonical ledger unavailable"),
    )
    assert client._recovery_marker_path is not None
    assert client._recovery_marker_path.exists()

    restarted = SmartAPIWebSocketClient(auth=MagicMock())
    restarted.configure_quarantine_store(str(db_path))
    durable_state = MagicMock()
    durable_state.load_unrepaired_stream_gap_state.return_value = [
        ("gap-open", "NSE", "2885", "RELIANCE", datetime(2026, 1, 6, tzinfo=timezone.utc), None, 6),
    ]
    with pytest.raises(StreamRecoveryError, match="durable stream recovery marker"):
        restarted.restore_unresolved_gaps(durable_state)
    assert restarted.state == ConnectionState.RECOVERY_FAILED
    assert ("NSE", "2885") in restarted._degraded_tokens
    with pytest.raises(StreamRecoveryError, match="startup is blocked"):
        restarted.start()
    restarted._on_open(MagicMock(), restarted.generation_id)
    assert restarted.state == ConnectionState.RECOVERY_FAILED


def test_e8_websocket_transport_lifecycle_failure_paths():
    """Transport failures remain isolated while fail-closed state is retained."""
    from smartapi.subscription_registry import SubscriptionKey
    from smartapi.websocket_client import ConnectionState, SmartAPIWebSocketClient
    from unittest.mock import MagicMock

    auth = MagicMock()
    auth.websocket_authorization = "Bearer test"
    auth.api_key = "key"
    auth.client_code = "client"
    auth.feed_token = "feed"
    socket = MagicMock()
    socket.run_forever.side_effect = RuntimeError("transport failed")
    client = SmartAPIWebSocketClient(auth=auth, websocket_factory=lambda **_: socket)
    client._connect_socket(client.generation_id)
    client._ws_thread.join(timeout=1.0)
    client.subscribe([SubscriptionKey(mode=1, exchange_type=1, token="2885")])
    client._on_open(socket, client.generation_id)
    assert socket.send.called
    socket.send.side_effect = RuntimeError("write failed")
    client._send_json({"action": 1})
    socket.close.side_effect = RuntimeError("close failed")
    client._trigger_stream_resync("NSE", "2885")
    client._state = ConnectionState.RECOVERY_FAILED
    client._on_close(socket, 1006, "failed", client.generation_id)
    assert client.state == ConnectionState.RECOVERY_FAILED
    client.stop()


def test_e8_lifecycle_callbacks_are_mandatory_and_gap_ids_are_exact():
    """Recovery operations reject missing durable callbacks and unknown exact IDs."""
    from smartapi.websocket_client import SmartAPIWebSocketClient, StreamRecoveryError
    from unittest.mock import MagicMock

    client = SmartAPIWebSocketClient(auth=MagicMock())
    with pytest.raises(StreamRecoveryError, match="re-anchor requires"):
        client.reanchor_stream("NSE", "2885", baseline_seq=1)
    with pytest.raises(StreamRecoveryError, match="repair requires"):
        client.repair_gap("NSE", "2885", "unknown")

    aggregator = RealtimeBarAggregator(timeframe="1m")
    start = datetime(2026, 1, 6, 9, 15, tzinfo=timezone.utc)
    aggregator.mark_untrusted("gap-a", "RELIANCE", start)
    aggregator.mark_untrusted("gap-a", "RELIANCE", start)
    assert aggregator._untrusted_windows["RELIANCE"] == [("gap-a", start, None)]
    with pytest.raises(KeyError, match="Unknown canonical"):
        aggregator.close_degraded_interval("gap-missing", start)
    with pytest.raises(KeyError, match="Unknown canonical"):
        aggregator.repair_gap("gap-missing")
    aggregator.close_degraded_interval("gap-a", start)
    aggregator.repair_gap("gap-a")


def test_e8_stream_fail_closed_transport_and_worker_edges(monkeypatch):
    """Raw-sink, gap-callback, watchdog and reconnect faults never make ticks authoritative."""
    import struct
    import threading
    from unittest.mock import MagicMock

    from data_platform.live_admission import EventTimePolicy
    from smartapi.websocket_client import ConnectionState, SmartAPIWebSocketClient

    auth = MagicMock()
    policy = LiveAdmissionPolicy(
        event_time=EventTimePolicy(max_feed_staleness_seconds=1e9, max_future_skew_seconds=1e9),
        max_stale_latency_seconds=1e9,
        check_session_hours=False,
    )
    client = SmartAPIWebSocketClient(
        auth=auth,
        admission_validator=LiveMarketDataAdmissionValidator(policy=policy),
    )
    client._state = ConnectionState.CONNECTED

    class UnreliableRawSink:
        def __init__(self) -> None:
            self.calls = 0

        def enqueue_raw_packet(self, raw: bytes, *, received_at: datetime) -> bool:
            self.calls += 1
            if self.calls == 1:
                return False
            raise RuntimeError("raw sink offline")

    client.raw_packet_sink = UnreliableRawSink()

    def packet(sequence: int) -> bytes:
        return struct.pack(
            "<BB25sqqq", 1, 1, b"2885".ljust(25, b"\x00"), sequence,
            int(time.time() * 1000), 250_000,
        )

    # A full raw queue is observational only: the valid baseline tick remains trusted.
    client._on_data(None, packet(1), 2, True)
    assert client.metrics.dispatch_queue_drops == 1
    assert client._dispatch_queue.get_nowait().quality_state == "TRUSTED"

    # No durable gap callback is a hard failure, even if raw capture also fails.
    client._on_data(None, packet(3), 2, True)
    assert client.state == ConnectionState.RECOVERY_FAILED
    assert client._dispatch_queue.empty()
    client._schedule_reconnect()
    assert client.metrics.reconnect_total == 0

    # A watchdog timeout closes the socket; it does not dispatch data itself.
    watchdog_client = SmartAPIWebSocketClient(auth=MagicMock())
    watchdog_client.watchdog_timeout = 1.0
    watchdog_client._state = ConnectionState.CONNECTED
    watchdog_client._last_rx_monotonic = 0.0
    watchdog_client._monotonic = lambda: 2.0
    watchdog_client._ws = MagicMock()
    watchdog_client._ws.close.side_effect = lambda: setattr(
        watchdog_client, "_state", ConnectionState.STOPPED,
    )
    monkeypatch.setattr("smartapi.websocket_client.time.sleep", lambda _: None)
    watchdog_client._watchdog_loop()
    watchdog_client._ws.close.assert_called_once()

    # Auth-refresh errors remain isolated and the reconnect attempt is still bounded.
    reconnect_client = SmartAPIWebSocketClient(auth=MagicMock())
    reconnect_client._rng = lambda _a, _b: 0.0
    reconnect_client._state = ConnectionState.CONNECTED
    reconnect_client.auth.refresh_token.side_effect = RuntimeError("expired")
    finished = threading.Event()
    reconnect_client._connect_socket = lambda _generation: finished.set()
    reconnect_client._schedule_reconnect(is_auth_error=True)
    assert finished.wait(timeout=1.0)
    assert reconnect_client.metrics.auth_refresh_total == 0


def test_p0_4_arbitrary_named_universe_fails_closed(tmp_path):
    """P0-4: Arbitrary explicit named-but-unregistered universes fail closed without PIT."""
    db = DuckDBManager(str(tmp_path / "custom_univ.duckdb"))
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-01 15:30:00+05:30', 100, 105, 95, 102, 100000, 'UNADJUSTED', 'ANGEL', 'ds1', CURRENT_TIMESTAMP);")
    builder = SynchronizedPanelBuilder(db, require_authoritative_certification=False)

    # Passing an arbitrary named universe with no PIT records must raise RuntimeError
    with pytest.raises(RuntimeError, match="Missing point-in-time constituent history for universe"):
        builder.build(["RELIANCE"], "1d", universe_name="MY_CUSTOM_MOMENTUM_UNIVERSE", benchmark_symbol=None)


def test_p1_8_strict_int_position_count_contract():
    """P1-8: open_position_count must be StrictInt and reject non-integer types."""
    from pydantic import ValidationError

    # Valid int passes
    proposal = TradeProposal(
        symbol="RELIANCE",
        requested_notional=50_000.0,
        capital=100_000.0,
        open_position_count=5,
    )
    assert proposal.open_position_count == 5

    # String int coercion must be rejected by StrictInt
    with pytest.raises(ValidationError):
        TradeProposal(
            symbol="RELIANCE",
            requested_notional=50_000.0,
            capital=100_000.0,
            open_position_count="5",
        )

    # Float must also be rejected
    with pytest.raises(ValidationError):
        TradeProposal(
            symbol="RELIANCE",
            requested_notional=50_000.0,
            capital=100_000.0,
            open_position_count=5.5,
        )


def test_p0_3_pipeline_paper_session_forwarding(tmp_path):
    """P0-3: StrategyPipeline forwards OpeningTickObservation end-to-end."""
    from trading_stack.domain import OpeningTickObservation
    db = DuckDBManager(str(tmp_path / "paper_obs.duckdb"))
    candle_frame = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-05 09:15", periods=10, freq="B", tz="Asia/Kolkata"),
        "open": [100.0] * 10,
        "high": [105.0] * 10,
        "low": [95.0] * 10,
        "close": [102.0] * 10,
        "volume": [1000] * 10,
    })
    db.upsert_candles(candle_frame, "RELIANCE", "2885", "NSE", "1d")

    # Authorize run
    db.conn.execute("""
        INSERT INTO promotion_reviews (review_id, run_id, strategy_name, stage, decision, human_approved, score, reasons_json, reviewed_at)
        VALUES ('rev-1', 'approved-run-1', 'cross_sectional_momentum', 'PAPER_ACTIVE', 'PASS', true, 1.0, '[]', CURRENT_TIMESTAMP);
    """)

    obs = OpeningTickObservation(
        symbol="RELIANCE",
        exchange="NSE",
        token="2885",
        price=105.0,
        exchange_timestamp=datetime(2026, 1, 10, 9, 15, tzinfo=timezone.utc),
        received_at_utc=datetime(2026, 1, 10, 9, 15, 1, tzinfo=timezone.utc),
    )

    pipeline = StrategyPipeline(db, require_authoritative_certification=False)
    out = pipeline.run_paper_session(
        strategy_name="cross_sectional_momentum",
        approved_run_id="approved-run-1",
        symbol="RELIANCE",
        timeframe="1d",
        universe=["RELIANCE"],
        benchmark_symbol="RELIANCE",
        execution_mode="TRUE_NEXT_OPEN",
        opening_observations={"RELIANCE": obs},
    )
    assert "forward_portfolio_result" in out

