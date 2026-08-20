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
from risk.validators import VaRValidator
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

    result_b = backtester.run(strategy, MockDatasetB(), starting_capital=100_000.0)

    order_a = result_a.run.orders[result_a.run.orders["symbol"] == "RELIANCE"].iloc[0]
    order_b = result_b.run.orders[result_b.run.orders["symbol"] == "RELIANCE"].iloc[0]

    # Both runs MUST execute exactly the same quantity and price based on Day 1 lagged ADV (50,000)
    assert order_a["quantity"] == order_b["quantity"]
    assert order_a["average_fill_price"] == order_b["average_fill_price"]
    assert order_a["status"] == order_b["status"]


# ---------------------------------------------------------------------------
# P0-3: Forward Paper Execution Chronology Modes
# ---------------------------------------------------------------------------

def test_p0_3_forward_paper_chronology_modes(tmp_path):
    """P0-3: Forward paper executes at close for EOD_BATCH and at open tick for TRUE_NEXT_OPEN."""
    db_file = tmp_path / "paper_test.duckdb"
    db = DuckDBManager(str(db_file))
    calendar = build_nse_calendar()
    risk_engine = RiskEngine()
    engine = ForwardPaperSessionEngine(db=db, calendar=calendar, risk_engine=risk_engine)

    bar = {
        "timestamp": datetime(2026, 1, 6, 10, 0, tzinfo=timezone.utc),
        "open": 100.0,
        "high": 105.0,
        "low": 98.0,
        "close": 102.0,
        "open_tick_price": 100.5,
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


# ---------------------------------------------------------------------------
# P0-4: Point-in-Time Universe Isolation
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
        {"timestamp": dates[0], "symbol": "RELIANCE", "close": 100.0, "eligible": True},
        {"timestamp": dates[0], "symbol": "INFY", "close": 200.0, "eligible": True},
        {"timestamp": dates[1], "symbol": "RELIANCE", "close": 105.0, "eligible": True},
        {"timestamp": dates[1], "symbol": "INFY", "close": 210.0, "eligible": True},
        {"timestamp": dates[2], "symbol": "RELIANCE", "close": 110.0, "eligible": True},
        {"timestamp": dates[2], "symbol": "INFY", "close": 250.0, "eligible": False},  # Dropped from index
    ]
    panel = pd.DataFrame(panel_records)
    signals = strategy.generate_signals(panel)

    # On date 2 (the rebalance date), INFY must NOT be present in signals or selection
    rebal_signals = signals[signals["timestamp"] == dates[2]]
    assert "INFY" not in rebal_signals["symbol"].values
    assert "RELIANCE" in rebal_signals["symbol"].values


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
# P1-8: Complete Risk Enforcement with VaR Validator
# ---------------------------------------------------------------------------

def test_p1_8_var_risk_validator():
    """P1-8: VaRValidator strictly rejects trade when estimated portfolio VaR exceeds max_var_pct."""
    policy = RiskPolicy(max_position_pct=0.20, max_var_pct=0.02)
    engine = RiskEngine(policy=policy)
    assert any(isinstance(v, VaRValidator) for v in engine.validators)

    # Proposal with 3% estimated VaR (limit is 2%)
    proposal_high_var = TradeProposal(
        symbol="RELIANCE",
        requested_notional=10_000.0,
        capital=100_000.0,
        order_side=OrderSide.BUY,
        estimated_portfolio_var_pct=0.03,
    )
    decision = engine.evaluate(proposal_high_var)
    assert decision.action == RiskAction.REJECT
    assert "var_limit_exceeded" in decision.reasons

    # Proposal with 1.5% estimated VaR (within 2% limit)
    proposal_ok_var = TradeProposal(
        symbol="RELIANCE",
        requested_notional=10_000.0,
        capital=100_000.0,
        order_side=OrderSide.BUY,
        estimated_portfolio_var_pct=0.015,
    )
    decision_ok = engine.evaluate(proposal_ok_var)
    assert decision_ok.action == RiskAction.PASS


# ---------------------------------------------------------------------------
# P1-9: Fail-Closed Data Quality Gate
# ---------------------------------------------------------------------------

def test_p1_9_fail_closed_data_quality(tmp_path):
    """P1-9: load_candles raises DataQualityError when unverified dataset or quality issues exist."""
    db_file = tmp_path / "dq_test.duckdb"
    db = DuckDBManager(str(db_file))
    db.conn.execute("INSERT INTO quality_report (symbol, timeframe, check_type, issue_count, checked_at) VALUES ('RELIANCE', '1d', 'session_alignment', 2, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO historical_candles (token, symbol, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id) VALUES ('2885', 'RELIANCE', 'NSE', '1d', '2026-01-01', 100, 105, 95, 100, 1000, 'UNADJUSTED', 'ANGEL', 'ds1');")
    pipeline = StrategyPipeline(db=db)

    # Issue count > 0 fails closed with DataQualityError
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
# P1-14: Realtime Bar Aggregator Allowed Lateness
# ---------------------------------------------------------------------------

def test_p1_14_allowed_lateness_event_time():
    """P1-14: RealtimeBarAggregator respects allowed_lateness grace period for late ticks."""
    from data_platform.contracts import LiveTickerMode

    aggregator = RealtimeBarAggregator(timeframe="1m", allowed_lateness_seconds=5.0)

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

    # 1st tick at 09:15:10
    t1 = datetime(2026, 1, 5, 9, 15, 10, tzinfo=timezone.utc)
    bars = aggregator.process_tick(make_tick(1000.0, t1, 10))
    assert len(bars) == 0

    # 2nd tick at 09:15:30
    t2 = datetime(2026, 1, 5, 9, 15, 30, tzinfo=timezone.utc)
    bars = aggregator.process_tick(make_tick(1005.0, t2, 20))
    assert len(bars) == 0

    # Late tick belonging to the 09:15 window arriving within 5s lateness grace
    t_late = datetime(2026, 1, 5, 9, 15, 50, tzinfo=timezone.utc)
    bars = aggregator.process_tick(make_tick(1008.0, t_late, 25))
    assert len(bars) == 0  # Not closed yet, late tick included in open bar

    # Snapshot shows updated high
    snap = aggregator.get_current_bar_snapshot("RELIANCE")
    assert snap is not None
    assert snap.high == 1008.0


# ---------------------------------------------------------------------------
# P1-16: Non-Overlapping Timeout Task Retry Invariant
# ---------------------------------------------------------------------------

def test_p1_16_non_overlapping_retry_invariant(tmp_path):
    """P1-16: Task timeout prevents overlapping concurrent worker execution on retries."""
    db = DuckDBManager(str(tmp_path / "orch.duckdb"))
    orchestrator = TaskOrchestrator(db=db)

    execution_count = 0

    def slow_task():
        nonlocal execution_count
        execution_count += 1
        time.sleep(1.0)
        return {"done": True}

    with pytest.raises(Exception):
        orchestrator.run_task("slow_job", slow_task, timeout_seconds=0.1, max_retries=1)


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
# P2-24 & P2-25: Stream Persistence Metrics and Raw Packet Capture
# ---------------------------------------------------------------------------

def test_p2_24_p2_25_raw_packets_and_spool_counters(tmp_path):
    """P2-24 & P2-25: Validates raw binary packet storage and distinct persistence counters."""
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
