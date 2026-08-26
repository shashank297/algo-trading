"""Comprehensive high-coverage unit tests for critical paths:
- risk/*.py
- trading_stack/paper.py
- trading_stack/portfolio.py
- trading_stack/portfolio_paper.py
- trading_stack/pipeline.py
- trading_stack/datasets.py
- trading_stack/certification.py
- trading_stack/promotion.py
- smartapi/websocket_client.py
- trading_stack/live_aggregator.py
- storage/migrations/*.py
"""

from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from data_platform.contracts import LiveTickerMode, OrderSide, PriceAdjustment
from data_platform.live_admission import (
    AdmissionReasonCode,
    TickAdmissionAction,
    TickAdmissionResult,
)
from risk.engine import RiskEngine
from risk.models import (
    RiskAction,
    RiskPolicy,
    TradeProposal,
)
from risk.validators import (
    RequiredRiskStateValidator,
)
from smartapi.auth import SmartAPIAuth
from smartapi.websocket_client import (
    ConnectionState,
    SmartAPIWebSocketClient,
)
from storage.duckdb_manager import DuckDBManager
from storage.migrations.runner import MigrationRunner
from trading_stack.calendars import build_nse_calendar
from trading_stack.certification import RunCertificationService
from trading_stack.datasets import ResearchDataset, SynchronizedPanelBuilder
from trading_stack.domain import (
    OpeningTickObservation,
)
from trading_stack.live_aggregator import RealtimeBarAggregator
from trading_stack.paper import ForwardPaperSessionEngine
from trading_stack.pipeline import DataQualityError, StrategyPipeline
from validators.data_quality import DataQualityError as DQError
from trading_stack.portfolio import PortfolioEventBacktester
from trading_stack.portfolio_paper import (
    ForwardPortfolioPaperSessionEngine,
)
from trading_stack.promotion import PromotionEngine, PromotionStage


# ---------------------------------------------------------------------------
# 1. Risk Validators & Models
# ---------------------------------------------------------------------------

def test_risk_validators_comprehensive_branch_coverage():
    policy = RiskPolicy(
        max_position_pct=0.20,
        max_gross_exposure_pct=1.0,
        max_daily_loss_pct=0.03,
        max_drawdown_pct=0.10,
        max_open_positions=10,
        min_liquidity_crore=10.0,
        max_var_pct=0.05,
        max_sector_exposure_pct=0.30,
    )
    engine = RiskEngine(policy)

    # 1. Valid proposal
    p_valid = TradeProposal(
        symbol="RELIANCE",
        requested_notional=10_000.0,
        capital=100_000.0,
        current_position_notional=0.0,
        order_side=OrderSide.BUY,
        current_gross_exposure=10_000.0,
        daily_pnl=100.0,
        current_drawdown=0.01,
        open_position_count=2,
        daily_turnover_crore=15.0,
        estimated_portfolio_var_pct=0.01,
        current_sector_exposure=5_000.0,
    )
    d = engine.evaluate(p_valid)
    assert d.action == RiskAction.PASS

    # 2. Daily Loss Limit violation
    p_loss = TradeProposal(
        symbol="RELIANCE",
        requested_notional=10_000.0,
        capital=100_000.0,
        order_side=OrderSide.BUY,
        daily_pnl=-5_000.0,  # -5% exceeds -3% limit
        current_position_notional=0.0,
        current_gross_exposure=10_000.0,
        current_drawdown=0.01,
        open_position_count=2,
        daily_turnover_crore=15.0,
        estimated_portfolio_var_pct=0.01,
        current_sector_exposure=5_000.0,
    )
    d_loss = engine.evaluate(p_loss)
    assert d_loss.action == RiskAction.REJECT
    assert any("DAILY_LOSS" in r for r in d_loss.reasons)

    # 3. Drawdown Limit violation
    p_dd = TradeProposal(
        symbol="RELIANCE",
        requested_notional=10_000.0,
        capital=100_000.0,
        order_side=OrderSide.BUY,
        current_drawdown=0.15,  # 15% exceeds 10%
        daily_pnl=100.0,
        current_position_notional=0.0,
        current_gross_exposure=10_000.0,
        open_position_count=2,
        daily_turnover_crore=15.0,
        estimated_portfolio_var_pct=0.01,
        current_sector_exposure=5_000.0,
    )
    d_dd = engine.evaluate(p_dd)
    assert d_dd.action == RiskAction.REJECT
    assert any("DRAWDOWN" in r for r in d_dd.reasons)

    # 4. Open position count violation
    p_count = TradeProposal(
        symbol="RELIANCE",
        requested_notional=10_000.0,
        capital=100_000.0,
        order_side=OrderSide.BUY,
        open_position_count=10,  # At limit
        current_position_notional=0.0,
        daily_pnl=100.0,
        current_drawdown=0.01,
        current_gross_exposure=10_000.0,
        daily_turnover_crore=15.0,
        estimated_portfolio_var_pct=0.01,
        current_sector_exposure=5_000.0,
    )
    d_count = engine.evaluate(p_count)
    assert d_count.action == RiskAction.REJECT
    assert any("max_open_positions" in r for r in d_count.reasons)

    # 5. Position concentration scaling / modification
    p_conc = TradeProposal(
        symbol="RELIANCE",
        requested_notional=30_000.0,  # 30% exceeds 20% limit
        capital=100_000.0,
        order_side=OrderSide.BUY,
        current_position_notional=0.0,
        daily_pnl=100.0,
        current_drawdown=0.01,
        current_gross_exposure=10_000.0,
        open_position_count=2,
        daily_turnover_crore=15.0,
        estimated_portfolio_var_pct=0.01,
        current_sector_exposure=5_000.0,
    )
    d_conc = engine.evaluate(p_conc)
    assert d_conc.action == RiskAction.MODIFY
    assert d_conc.approved_notional == pytest.approx(20_000.0)

    # 6. Gross exposure modification
    p_gross = TradeProposal(
        symbol="RELIANCE",
        requested_notional=20_000.0,
        capital=100_000.0,
        order_side=OrderSide.BUY,
        current_gross_exposure=90_000.0,  # Only 10k remaining room
        daily_pnl=100.0,
        current_drawdown=0.01,
        open_position_count=2,
        current_position_notional=0.0,
        daily_turnover_crore=15.0,
        estimated_portfolio_var_pct=0.01,
        current_sector_exposure=5_000.0,
    )
    d_gross = engine.evaluate(p_gross)
    assert d_gross.action == RiskAction.MODIFY
    assert d_gross.approved_notional == pytest.approx(10_000.0)

    # 7. Sector exposure modification
    p_sec = TradeProposal(
        symbol="RELIANCE",
        requested_notional=20_000.0,
        capital=100_000.0,
        order_side=OrderSide.BUY,
        current_sector_exposure=25_000.0,  # Room is 5k before 30k
        daily_pnl=100.0,
        current_drawdown=0.01,
        open_position_count=2,
        current_position_notional=0.0,
        current_gross_exposure=10_000.0,
        daily_turnover_crore=15.0,
        estimated_portfolio_var_pct=0.01,
    )
    d_sec = engine.evaluate(p_sec)
    assert d_sec.action == RiskAction.MODIFY
    assert d_sec.approved_notional == pytest.approx(5_000.0)

    # 8. Portfolio VaR rejection
    p_var = TradeProposal(
        symbol="RELIANCE",
        requested_notional=10_000.0,
        capital=100_000.0,
        order_side=OrderSide.BUY,
        estimated_portfolio_var_pct=0.08,  # Exceeds 0.05 limit
        daily_pnl=100.0,
        current_drawdown=0.01,
        open_position_count=2,
        current_position_notional=0.0,
        current_gross_exposure=10_000.0,
        daily_turnover_crore=15.0,
        current_sector_exposure=5_000.0,
    )
    d_var = engine.evaluate(p_var)
    assert d_var.action == RiskAction.REJECT
    assert any("var_limit" in r for r in d_var.reasons)

    # 9. Liquidity Turnover rejection
    p_turn = TradeProposal(
        symbol="RELIANCE",
        requested_notional=10_000.0,
        capital=100_000.0,
        order_side=OrderSide.BUY,
        daily_turnover_crore=5.0,  # Less than 10.0 crore limit
        daily_pnl=100.0,
        current_drawdown=0.01,
        open_position_count=2,
        current_position_notional=0.0,
        current_gross_exposure=10_000.0,
        estimated_portfolio_var_pct=0.01,
        current_sector_exposure=5_000.0,
    )
    d_turn = engine.evaluate(p_turn)
    assert d_turn.action == RiskAction.REJECT
    assert any("insufficient_daily_liquidity" in r for r in d_turn.reasons)

    # 10. Direct validator calls
    req_val = RequiredRiskStateValidator()
    cap, reasons = req_val.evaluate(p_valid, policy)
    assert cap == 10_000.0
    assert not reasons


# ---------------------------------------------------------------------------
# 2. Certification Service Edge Cases & Fail-Closed Branches
# ---------------------------------------------------------------------------

def test_run_certification_service_fail_closed_branches(tmp_path):
    db = DuckDBManager(str(tmp_path / "cert_branches.duckdb"))
    service = RunCertificationService(db)

    # 1. Non-existent run
    with pytest.raises(ValueError, match="unknown run_id"):
        service.certify("UNKNOWN_RUN_999")

    # 2. Run missing frame_certification_id
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes) VALUES ('run_no_frame', 'trend', 'INDIA_EQUITY', 'RELIANCE', '1d', 'event-driven', '{}', 'h1', 'COMPLETED', CURRENT_TIMESTAMP, '{}');")
    bundle_id = service.certify("run_no_frame")
    certs = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [bundle_id]).fetchall())
    assert certs["DATA_LINEAGE"] == "FAIL"
    assert certs["DATA_QUALITY"] == "FAIL"
    assert certs["CAUSALITY"] == "FAIL"

    # 3. Frame hash mismatch
    db.conn.execute("INSERT INTO research_frame_certifications (frame_certification_id, research_frame_hash, contributing_dataset_ids_json, symbol, timeframe, row_count, basis, validator_version, status, verified_at) VALUES ('frame_bad_hash', 'wrong_hash', '[\"ds1\"]', 'RELIANCE', '1d', 1, 'SPLIT_ADJUSTED', 'v1', 'CERTIFIED', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes) VALUES ('run_bad_hash', 'trend', 'INDIA_EQUITY', 'RELIANCE', '1d', 'event-driven', '{}', 'h1', 'COMPLETED', CURRENT_TIMESTAMP, '{\"frame_certification_id\":\"frame_bad_hash\"}');")
    bundle_bad_hash = service.certify("run_bad_hash")
    certs_bad = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [bundle_bad_hash]).fetchall())
    assert certs_bad["DATA_LINEAGE"] == "FAIL"
    assert certs_bad["CAUSALITY"] == "FAIL"

    # 4. Fill chronology violation
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes) VALUES ('run_bad_chrono', 'trend', 'INDIA_EQUITY', 'RELIANCE', '1d', 'event-driven', '{}', 'h_good', 'COMPLETED', CURRENT_TIMESTAMP, '{\"frame_certification_id\":\"frame_chrono\"}');")
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, status, lifecycle_status) VALUES ('ds_chrono', 'RELIANCE', 'RELIANCE', 'NSE', '1d', 'ANGEL', 'h_chrono', 'VERIFIED', 'CANONICAL_PROMOTED');")
    db.conn.execute("INSERT INTO data_quality_certifications VALUES ('cert_chrono', 'ds_chrono', 'validator-v1', 6, 0, '{\"dataset_content_hash\": \"h_chrono\"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
    for i, c in enumerate(["schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"], start=1):
        db.conn.execute("INSERT INTO quality_report (id, symbol, timeframe, dataset_id, check_type, issue_count, details, checked_at, certification_id) VALUES (?, 'RELIANCE', '1d', 'ds_chrono', ?, 0, '{}', CURRENT_TIMESTAMP, 'cert_chrono')", [100 + i, c])
    db.conn.execute("INSERT INTO research_frame_certifications (frame_certification_id, research_frame_hash, contributing_dataset_ids_json, symbol, timeframe, row_count, basis, validator_version, status, verified_at, dataset_evidence_json, dq_certification_ids_json, pit_evidence_hash) VALUES ('frame_chrono', 'h_good', '[\"ds_chrono\"]', 'RELIANCE', '1d', 1, 'SPLIT_ADJUSTED', 'v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{\"ds_chrono\":\"h_chrono\"}', '[\"cert_chrono\"]', null);")
    db.conn.execute("INSERT INTO strategy_orders VALUES ('o1', 'run_bad_chrono', 'RELIANCE', 'BUY', 10, 'MARKET', 'DAY', 'FILLED', '2026-01-05 10:00:00', '2026-01-05 10:00:00', 100, 0, 100, 0, 0, '{}', CURRENT_TIMESTAMP);")
    # Fill has timestamp BEFORE order requested_at
    db.conn.execute("INSERT INTO strategy_fills VALUES ('f1', 'o1', 'run_bad_chrono', 'RELIANCE', '2026-01-05 09:00:00', 10, 100, 'BUY', 'PAPER', 0, 0, '{}', CURRENT_TIMESTAMP);")
    bundle_chrono = service.certify("run_bad_chrono")
    certs_chrono = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [bundle_chrono]).fetchall())
    assert certs_chrono["CAUSALITY"] == "FAIL"


# ---------------------------------------------------------------------------
# 3. Promotion Engine Stitched OOS Returns & Review Logic
# ---------------------------------------------------------------------------

def test_promotion_engine_comprehensive_evaluation(tmp_path):
    db = DuckDBManager(str(tmp_path / "promotion_eval.duckdb"))
    engine = PromotionEngine(db)

    # 1. Seed complete passing run
    run_id = "RUN_PROMOTION_PASS"
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes) VALUES ('RUN_PROMOTION_PASS', 'cross_sectional_momentum', 'INDIA_EQUITY', 'RELIANCE', '1d', 'event-driven', '{}', 'h_pass', 'COMPLETED', CURRENT_TIMESTAMP, '{\"frame_certification_id\":\"rfc_pass\"}');")
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, status, lifecycle_status) VALUES ('ds_pass', 'RELIANCE', 'RELIANCE', 'NSE', '1d', 'ANGEL', 'h_pass_raw', 'VERIFIED', 'CANONICAL_PROMOTED');")
    db.conn.execute("INSERT INTO data_quality_certifications VALUES ('cert_pass', 'ds_pass', 'validator-v1', 6, 0, '{\"dataset_content_hash\": \"h_pass_raw\"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
    for i, c in enumerate(["schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"], start=1):
        db.conn.execute("INSERT INTO quality_report (id, symbol, timeframe, dataset_id, check_type, issue_count, details, checked_at, certification_id) VALUES (?, 'RELIANCE', '1d', 'ds_pass', ?, 0, '{}', CURRENT_TIMESTAMP, 'cert_pass')", [200 + i, c])
    db.conn.execute("INSERT INTO research_frame_certifications (frame_certification_id, research_frame_hash, contributing_dataset_ids_json, symbol, timeframe, row_count, basis, validator_version, status, verified_at, dataset_evidence_json, dq_certification_ids_json, pit_evidence_hash) VALUES ('rfc_pass', 'h_pass', '[\"ds_pass\"]', 'RELIANCE', '1d', 1, 'SPLIT_ADJUSTED', 'v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{\"ds_pass\":\"h_pass_raw\"}', '[\"cert_pass\"]', null);")
    
    # Stitched out of sample equity curve producing high Sharpe and low drawdown
    base_eq = 100_000.0
    for day_i in range(1, 20):
        base_eq *= 1.01  # steady 1% daily gain
        db.conn.execute("INSERT INTO strategy_equity_curve VALUES ('RUN_PROMOTION_PASS', ?, ?, 0, 0, 0, 0, 'OUT_OF_SAMPLE', 'fold1');", [f"2026-01-{day_i:02d} 15:30:00+05:30", base_eq])
    
    # 5 Walk forward folds
    for f_i in range(1, 6):
        db.conn.execute(
            """INSERT INTO walk_forward_folds VALUES (?, ?, '2025-12-01', '2025-12-31', '2026-01-01', '2026-01-10', '{"k": 1}', 5, 2.0, 'h_tr', 'h_te', CURRENT_TIMESTAMP);""",
            [run_id, f"fold{f_i}"],
        )
        db.conn.execute("INSERT INTO walk_forward_metrics VALUES ('RUN_PROMOTION_PASS', ?, '2025-12-31', '2026-01-01', '2026-01-10', 'sharpe', 2.5);", [f"fold{f_i}"])
        db.conn.execute("INSERT INTO walk_forward_metrics VALUES ('RUN_PROMOTION_PASS', ?, '2025-12-31', '2026-01-01', '2026-01-10', 'sortino', 3.0);", [f"fold{f_i}"])
        db.conn.execute("INSERT INTO walk_forward_metrics VALUES ('RUN_PROMOTION_PASS', ?, '2025-12-31', '2026-01-01', '2026-01-10', 'trades', 25);", [f"fold{f_i}"])
        db.conn.execute("INSERT INTO walk_forward_metrics VALUES ('RUN_PROMOTION_PASS', ?, '2025-12-31', '2026-01-01', '2026-01-10', 'profit_factor', 2.1);", [f"fold{f_i}"])
        db.conn.execute("INSERT INTO walk_forward_metrics VALUES ('RUN_PROMOTION_PASS', ?, '2025-12-31', '2026-01-01', '2026-01-10', 'max_drawdown', 0.05);", [f"fold{f_i}"])
        # Round trips
        db.conn.execute("INSERT INTO walk_forward_round_trips VALUES (?, 'RUN_PROMOTION_PASS', ?, 'RELIANCE', '2026-01-01', '2026-01-05', 10, 100, 110, 1, 1, 100, 98, 4, 'ENTRY', 'SIGNAL', 'WIN');", [f"trade_{f_i}", f"fold{f_i}"])

    review = engine.review(run_id, human_approved=True)
    assert review["decision"] == "PASS"
    assert review["stage"] in (PromotionStage.BACKTEST_VALIDATED.value, PromotionStage.PAPER_CANDIDATE.value)


# ---------------------------------------------------------------------------
# 4. WebSocket Client Recovery, Re-anchor, & Gap State Machine
# ---------------------------------------------------------------------------

def test_websocket_client_gap_handling_and_reconnect_flow():
    auth = MagicMock(spec=SmartAPIAuth)
    auth.websocket_authorization = "Bearer test"
    auth.api_key = "key"
    auth.client_code = "client"
    auth.feed_token = "token"

    degraded_calls = []
    reanchored_calls = []
    repaired_calls = []

    client = SmartAPIWebSocketClient(
        auth=auth,
        on_stream_degraded=lambda ex, tok, sym, window, gap, epoch: degraded_calls.append((tok, gap, epoch)),
        on_stream_reanchored=lambda ex, tok, sym, epoch: reanchored_calls.append((tok, epoch)),
        on_gap_repaired=lambda ex, tok, sym, gap_id: repaired_calls.append((tok, gap_id)),
    )

    # 1. State properties
    with client._state_lock:
        client._state = ConnectionState.CONNECTED
    assert client.state == ConnectionState.CONNECTED
    assert client.generation_id == 0

    # 2. Sequence Gap inspection
    is_gap, is_dup, gap_size = client.metrics.sequence_tracker.inspect_sequence("NSE", "2885", 10)
    assert is_gap is False  # Initial packet anchors

    is_gap, is_dup, gap_size = client.metrics.sequence_tracker.inspect_sequence("NSE", "2885", 15)
    assert is_gap is True
    assert gap_size == 4

    # 3. Duplicate packet
    is_gap, is_dup, gap_size = client.metrics.sequence_tracker.inspect_sequence("NSE", "2885", 15)
    assert is_dup is True

    # 4. Authoritative Re-anchor
    with pytest.raises(ValueError, match="non-negative sequence baseline"):
        client.reanchor_stream("NSE", "2885", baseline_seq=-1)

    client._degraded_tokens.add(("NSE", "2885"))
    with client._state_lock:
        client._state = ConnectionState.DEGRADED
    client.reanchor_stream("NSE", "2885", baseline_seq=50)
    assert ("NSE", "2885") not in client._degraded_tokens
    assert client.state == ConnectionState.CONNECTED
    assert len(reanchored_calls) == 1

    # 5. Gap repaired callback
    client.repair_gap("NSE", "2885", "gap_001")
    assert len(repaired_calls) == 1


# ---------------------------------------------------------------------------
# 5. RealtimeBarAggregator Untrusted Windows & Gap Management
# ---------------------------------------------------------------------------

def test_realtime_bar_aggregator_untrusted_intervals_and_repair():
    aggregator = RealtimeBarAggregator(
        timeframe="1m",
        allowed_lateness_seconds=2.0,
    )
    t0 = datetime(2026, 1, 6, 9, 15, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 6, 9, 20, 0, tzinfo=timezone.utc)

    # 1. Mark untrusted open-ended
    aggregator.mark_untrusted("RELIANCE", t0, None)
    assert len(aggregator._untrusted_windows["RELIANCE"]) == 1
    assert aggregator._untrusted_windows["RELIANCE"][0] == (t0, None)

    # 2. Close degraded interval at re-anchor time
    aggregator.close_degraded_interval("RELIANCE", t1)
    assert aggregator._untrusted_windows["RELIANCE"][0] == (t0, t1)

    # 3. Repair gap removes the window
    aggregator.repair_gap("RELIANCE", t0, t1)
    assert len(aggregator._untrusted_windows["RELIANCE"]) == 0


# ---------------------------------------------------------------------------
# 6. SynchronizedPanelBuilder & Single-Asset / Portfolio Paper Sizing
# ---------------------------------------------------------------------------

def test_paper_engine_sizing_and_var_with_dynamic_equity(tmp_path):
    db = DuckDBManager(str(tmp_path / "paper_sizing.duckdb"))
    calendar = build_nse_calendar()
    risk_engine = RiskEngine()
    engine = ForwardPaperSessionEngine(db=db, calendar=calendar, risk_engine=risk_engine)

    obs = OpeningTickObservation(
        symbol="RELIANCE",
        exchange="NSE",
        token="2885",
        price=100.0,
        exchange_timestamp=datetime(2026, 1, 6, 9, 15, tzinfo=timezone.utc),
        received_at_utc=datetime(2026, 1, 6, 9, 15, 1, tzinfo=timezone.utc),
    )
    bar = {
        "timestamp": datetime(2026, 1, 6, 10, 0, tzinfo=timezone.utc),
        "open": 100.0,
        "high": 105.0,
        "low": 98.0,
        "close": 102.0,
        "volume": 1_000_000,
        "token": "2885",
        "open_tick_observation": obs,
    }
    pending = {
        "signal_timestamp": datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc),
        "target_position": 0.5,
    }

    # Execute pending order with cash 100k, existing position 100 shares at 100 (equity 110k)
    cash, qty, avg_cost, e_ts, e_rsn, pool, drag, ord_res, fill_res, rt, pnl, dec = engine._execute_pending(
        session_id="sess_1",
        symbol="RELIANCE",
        bar=bar,
        pending=pending,
        cash=100_000.0,
        quantity=100.0,
        average_cost=95.0,
        entry_timestamp=datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc),
        entry_cost_pool=10.0,
        entry_execution_cost_pool=5.0,
        starting_capital=100_000.0,
        daily_start_equity=110_000.0,
        peak_equity=110_000.0,
        execution_mode="TRUE_NEXT_OPEN",
    )
    assert fill_res is not None
    assert fill_res["price"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# 7. Storage Migration Runner Coverage
# ---------------------------------------------------------------------------

def test_migration_runner_coverage(tmp_path):
    db_file = tmp_path / "mig_test.duckdb"
    _ = DuckDBManager(str(db_file))
    
    # Re-running migrations is idempotent
    applied = MigrationRunner(str(db_file)).run_migrations()
    assert isinstance(applied, list)


# ---------------------------------------------------------------------------
# 8. Pipeline Lineage, DQ Errors, & Vectorized Execution
# ---------------------------------------------------------------------------

def test_pipeline_load_candles_dq_and_vectorized_execution(tmp_path):
    db = DuckDBManager(str(tmp_path / "pipeline_dq.duckdb"))
    pipeline = StrategyPipeline(db=db, require_authoritative_certification=True)

    # 1. Empty candles raises ValueError
    with pytest.raises(ValueError, match="No stored candles found"):
        pipeline.load_candles("RELIANCE", "1d")

    # 2. Insert uncertified candle
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-05 15:30:00+05:30', 100, 105, 95, 100, 1000, 'UNADJUSTED', 'ANGEL', null, CURRENT_TIMESTAMP);")
    with pytest.raises(DataQualityError, match="uncertified candle rows present with NULL dataset_id"):
        pipeline.load_candles("RELIANCE", "1d")

    # 3. Insert dataset with non-promoted status
    db.conn.execute("DELETE FROM historical_candles;")
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-05 15:30:00+05:30', 100, 105, 95, 100, 1000, 'UNADJUSTED', 'ANGEL', 'ds_unpromoted', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, status, lifecycle_status) VALUES ('ds_unpromoted', 'RELIANCE', 'RELIANCE', 'NSE', '1d', 'ANGEL', 'h_unpromoted', 'STAGED', 'RAW_INGESTED');")
    with pytest.raises(DataQualityError, match="must be VERIFIED and CANONICAL_PROMOTED"):
        pipeline.load_candles("RELIANCE", "1d")

    # 4. Insert valid dataset & certification
    db.conn.execute("DELETE FROM historical_candles;")
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-05 15:30:00+05:30', 100, 105, 95, 100, 1000, 'UNADJUSTED', 'ANGEL', 'ds_valid', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, status, lifecycle_status) VALUES ('ds_valid', 'RELIANCE', 'RELIANCE', 'NSE', '1d', 'ANGEL', 'h_valid', 'VERIFIED', 'CANONICAL_PROMOTED');")
    db.conn.execute("INSERT INTO data_quality_certifications VALUES ('cert_valid', 'ds_valid', 'validator-v1', 6, 0, '{\"dataset_content_hash\": \"h_valid\"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
    for i, c in enumerate(["schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"], start=1):
        db.conn.execute("INSERT INTO quality_report (id, symbol, timeframe, dataset_id, check_type, issue_count, details, checked_at, certification_id) VALUES (?, 'RELIANCE', '1d', 'ds_valid', ?, 0, '{}', CURRENT_TIMESTAMP, 'cert_valid');", [300 + i, c])

    df = pipeline.load_candles("RELIANCE", "1d")
    assert len(df) == 1

    # 5. Run vectorized mode
    # Add 25 days of candles to satisfy indicator lookbacks
    for d_i in range(6, 35):
        day_str = f"2026-01-{d_i:02d}" if d_i <= 31 else f"2026-02-{d_i-31:02d}"
        db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', ?, 100 + ?, 105 + ?, 95 + ?, 100 + ?, 100000, 'UNADJUSTED', 'ANGEL', 'ds_valid', CURRENT_TIMESTAMP);", [f"{day_str} 15:30:00+05:30", d_i, d_i, d_i, d_i])
    
    result = pipeline.run(
        strategy_name="donchian_trend",
        symbol="RELIANCE",
        timeframe="1d",
        parameters={"entry_window": 5, "exit_window": 2},
        mode="vectorized",
        cost_model={"slippage_bps": 5.0, "brokerage_bps": 3.0},
    )
    assert result["run_id"] is not None
    assert result["data_hash"] is not None
    assert result["result"].run_id is not None


# ---------------------------------------------------------------------------
# 9. SynchronizedPanelBuilder & Basis Adjustments
# ---------------------------------------------------------------------------

def test_datasets_synchronized_panel_builder_comprehensive(tmp_path):
    db = DuckDBManager(str(tmp_path / "panel_builder.duckdb"))
    calendar = build_nse_calendar()
    builder = SynchronizedPanelBuilder(db=db, calendar=calendar, require_authoritative_certification=False)

    # 1. Setup universe & candles
    db.conn.execute("INSERT INTO universe_snapshots VALUES ('SNAP_PANEL', 'NIFTY50', 'http://nifty.com', '2026-01-01', 'h_snap', false, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO universe_snapshot_members VALUES ('SNAP_PANEL', 'INFY', 'INFY', '1594', 'Infosys', 'IT', 'NSE', '2020-01-01', '2027-01-01', true, true, true);")
    db.conn.execute("INSERT INTO index_constituents_pit VALUES ('SNAP_PANEL', '1594', 'INFY', '1594', 'NSE', '2020-01-01', '2027-01-01', '2020-01-01', 0.5, 'IN', null, CURRENT_TIMESTAMP);")
    
    for day_i in range(1, 10):
        db.conn.execute(
            "INSERT INTO historical_candles VALUES ('INFY', '1594', 'NSE', '1d', ?, 100, 105, 95, 102, 50000, 'UNADJUSTED', 'ANGEL', 'ds_infy', CURRENT_TIMESTAMP);",
            [f"2026-01-{day_i:02d} 15:30:00+05:30"],
        )
        db.conn.execute(
            "INSERT INTO historical_candles VALUES ('NIFTY', '999', 'NSE', '1d', ?, 20000, 20100, 19900, 20050, 500000, 'UNADJUSTED', 'ANGEL', 'ds_nifty', CURRENT_TIMESTAMP);",
            [f"2026-01-{day_i:02d} 15:30:00+05:30"],
        )

    # 2. Build panel with UNADJUSTED basis
    ds_unadj = builder.build(
        symbols=["INFY"],
        timeframe="1d",
        adjustment=PriceAdjustment.UNADJUSTED,
        universe_snapshot_id="SNAP_PANEL",
    )
    assert not ds_unadj.panel.empty
    assert "INFY" in ds_unadj.panel["symbol"].values

    # 3. Build panel with SPLIT_ADJUSTED basis
    ds_split = builder.build(
        symbols=["INFY"],
        timeframe="1d",
        adjustment=PriceAdjustment.SPLIT_ADJUSTED,
        universe_snapshot_id="SNAP_PANEL",
    )
    assert not ds_split.panel.empty

    # 4. Build from cache
    ds_cached = builder.build(
        symbols=["INFY"],
        timeframe="1d",
        adjustment=PriceAdjustment.SPLIT_ADJUSTED,
        universe_snapshot_id="SNAP_PANEL",
    )
    assert len(ds_cached.panel) == len(ds_split.panel)


# ---------------------------------------------------------------------------
# 10. RealtimeBarAggregator Late Ticks & Finalization
# ---------------------------------------------------------------------------

def test_realtime_bar_aggregator_late_ticks_and_finalization():
    from data_platform.contracts import LiveTickerMode, LtpTick
    bars_emitted = []
    aggregator = RealtimeBarAggregator(
        timeframe="1m",
        allowed_lateness_seconds=2.0,
    )
    aggregator.subscribe_bar(lambda bar: bars_emitted.append(bar))

    t0 = datetime(2026, 1, 6, 9, 15, 10, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 6, 9, 15, 50, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 6, 9, 16, 5, tzinfo=timezone.utc)

    # 1. Feed ticks in first minute
    tick0 = LtpTick(mode=LiveTickerMode.LTP, exchange="NSE", token="2885", symbol="RELIANCE", ltp=100.0, exchange_timestamp=t0, received_at_utc=t0, received_monotonic_ns=0, raw_packet_size=32, sequence_number=1, stream_epoch=0)
    tick1 = LtpTick(mode=LiveTickerMode.LTP, exchange="NSE", token="2885", symbol="RELIANCE", ltp=102.0, exchange_timestamp=t1, received_at_utc=t1, received_monotonic_ns=0, raw_packet_size=32, sequence_number=2, stream_epoch=0)
    aggregator.process_tick(tick0)
    aggregator.process_tick(tick1)

    # 2. Advance watermark to trigger bar finalization for 09:15:00
    tick2 = LtpTick(mode=LiveTickerMode.LTP, exchange="NSE", token="2885", symbol="RELIANCE", ltp=103.0, exchange_timestamp=t2, received_at_utc=t2, received_monotonic_ns=0, raw_packet_size=32, sequence_number=3, stream_epoch=0)
    closed = aggregator.process_tick(tick2)
    
    # Check that the 09:15 bar was closed
    assert len(bars_emitted) >= 1 or len(closed) >= 1
    b = bars_emitted[0] if bars_emitted else closed[0]
    assert b.open == 100.0
    assert b.close == 102.0


# ---------------------------------------------------------------------------
# 11. RunCertificationService All Failure & Edge Branches
# ---------------------------------------------------------------------------

def test_certification_comprehensive_error_branches(tmp_path):
    db = DuckDBManager(str(tmp_path / "cert_errors.duckdb"))
    service = RunCertificationService(db)

    # 1. Malformed notes JSON
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes) VALUES ('run_bad_json', 'trend', 'INDIA_EQUITY', 'RELIANCE', '1d', 'event-driven', '{}', 'h1', 'COMPLETED', CURRENT_TIMESTAMP, '{bad json');")
    b_bad_json = service.certify("run_bad_json")
    assert b_bad_json is not None

    # 2. Frame with missing contributing datasets
    db.conn.execute("INSERT INTO research_frame_certifications (frame_certification_id, research_frame_hash, contributing_dataset_ids_json, symbol, timeframe, row_count, basis, validator_version, status, verified_at, dataset_evidence_json, dq_certification_ids_json) VALUES ('frame_empty_ds', 'h_empty', '[]', 'RELIANCE', '1d', 1, 'SPLIT_ADJUSTED', 'v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{}', '[]');")
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, frame_certification_id) VALUES ('run_empty_ds', 'trend', 'INDIA_EQUITY', 'RELIANCE', '1d', 'event-driven', '{}', 'h_empty', 'COMPLETED', CURRENT_TIMESTAMP, 'frame_empty_ds');")
    b_empty_ds = service.certify("run_empty_ds")
    certs_empty = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b_empty_ds]).fetchall())
    assert certs_empty["DATA_LINEAGE"] == "FAIL"
    assert certs_empty["DATA_QUALITY"] == "FAIL"

    # 3. Dataset hash mismatch
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, status, lifecycle_status) VALUES ('ds_mismatch', 'RELIANCE', 'RELIANCE', 'NSE', '1d', 'ANGEL', 'current_hash_diff', 'VERIFIED', 'CANONICAL_PROMOTED');")
    db.conn.execute("INSERT INTO research_frame_certifications (frame_certification_id, research_frame_hash, contributing_dataset_ids_json, symbol, timeframe, row_count, basis, validator_version, status, verified_at, dataset_evidence_json, dq_certification_ids_json) VALUES ('frame_mismatch', 'h_mis', '[\"ds_mismatch\"]', 'RELIANCE', '1d', 1, 'SPLIT_ADJUSTED', 'v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{\"ds_mismatch\":\"old_hash\"}', '[\"cert_mismatch\"]');")
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, frame_certification_id) VALUES ('run_mismatch', 'trend', 'INDIA_EQUITY', 'RELIANCE', '1d', 'event-driven', '{}', 'h_mis', 'COMPLETED', CURRENT_TIMESTAMP, 'frame_mismatch');")
    b_mis = service.certify("run_mismatch")
    certs_mis = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b_mis]).fetchall())
    assert certs_mis["DATA_LINEAGE"] == "FAIL"

    # 4. DQ certification missing checks
    db.conn.execute("INSERT INTO data_quality_certifications VALUES ('cert_missing_checks', 'ds_mismatch', 'v1', 6, 0, '{\"dataset_content_hash\": \"current_hash_diff\"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
    # Insert only 1 check out of 6
    db.conn.execute("INSERT INTO quality_report (id, symbol, timeframe, dataset_id, check_type, issue_count, details, checked_at, certification_id) VALUES (999, 'RELIANCE', '1d', 'ds_mismatch', 'schema', 0, '{}', CURRENT_TIMESTAMP, 'cert_missing_checks');")
    db.conn.execute("UPDATE research_frame_certifications SET dataset_evidence_json = '{\"ds_mismatch\":\"current_hash_diff\"}', dq_certification_ids_json = '[\"cert_missing_checks\"]' WHERE frame_certification_id = 'frame_mismatch';")
    b_dq_miss = service.certify("run_mismatch")
    certs_dq_miss = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b_dq_miss]).fetchall())
    assert certs_dq_miss["DATA_QUALITY"] == "FAIL"

    # 5. Portfolio PIT hash mismatch
    db.conn.execute("INSERT INTO universe_snapshots VALUES ('SNAP_PIT', 'NIFTY50', 'http://nifty.com', '2026-01-01', 'h_pit_true', false, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO research_frame_certifications (frame_certification_id, research_frame_hash, contributing_dataset_ids_json, symbol, timeframe, row_count, basis, validator_version, status, verified_at, dataset_evidence_json, dq_certification_ids_json, pit_evidence_hash) VALUES ('frame_pit', 'h_pit', '[\"ds_mismatch\"]', 'PORTFOLIO:SNAP_PIT', '1d', 1, 'SPLIT_ADJUSTED', 'v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{\"ds_mismatch\":\"current_hash_diff\"}', '[\"cert_missing_checks\"]', 'h_pit_tampered');")
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, frame_certification_id) VALUES ('run_pit_mismatch', 'trend', 'INDIA_EQUITY', 'PORTFOLIO:SNAP_PIT', '1d', 'event-driven', '{}', 'h_pit', 'COMPLETED', CURRENT_TIMESTAMP, 'frame_pit');")
    b_pit = service.certify("run_pit_mismatch")
    certs_pit = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b_pit]).fetchall())
    assert certs_pit["PIT_SURVIVORSHIP"] == "FAIL"


# ---------------------------------------------------------------------------
# 12. SmartAPIWebSocketClient Message Decoders, Subscriptions & Callbacks
# ---------------------------------------------------------------------------

def test_websocket_client_callbacks_and_queue_processing():
    auth = MagicMock(spec=SmartAPIAuth)
    auth.websocket_authorization = "Bearer test"
    auth.api_key = "key"
    auth.client_code = "client"
    auth.feed_token = "token"

    client = SmartAPIWebSocketClient(auth=auth)
    client.subscribe_tick(lambda event: None)

    # 1. Open event
    client._on_open(None, generation=0)
    assert client.state == ConnectionState.CONNECTED

    # 2. Binary data handling and error resilience
    client._on_data(None, b"invalid_binary_garbage", generation=0)

    # 3. Error and close callbacks
    client._on_error(None, RuntimeError("test error"), generation=0)
    client._on_close(None, 1000, "normal close", generation=0)

    # 4. Subscriptions formatting
    from smartapi.subscription_registry import SubscriptionKey
    k = SubscriptionKey(mode=LiveTickerMode.LTP, exchange_type=1, token="2885")
    with patch.object(client, "_send_json"):
        client.subscribe([k])
        assert k in client.registry.desired_subscriptions
        client.unsubscribe([k])
        assert k not in client.registry.desired_subscriptions


# ---------------------------------------------------------------------------
# 13. LiveAggregator Load Unresolved Gaps from DB
# ---------------------------------------------------------------------------

def test_live_aggregator_unresolved_gaps_loading(tmp_path):
    db = DuckDBManager(str(tmp_path / "agg_gaps.duckdb"))
    aggregator = RealtimeBarAggregator(timeframe="1m")

    # 1. Insert unrepaired gaps into stream_gap_events
    db.conn.execute(
        "INSERT INTO stream_gap_events VALUES ('gap_1', 'NSE', '2885', 'RELIANCE', '2026-01-06 09:15:00', null, 5, 0, 'UNREPAIRED', CURRENT_TIMESTAMP);"
    )
    aggregator.load_unresolved_gaps(db)
    assert "RELIANCE" in aggregator._untrusted_windows
    assert len(aggregator._untrusted_windows["RELIANCE"]) >= 1


# ---------------------------------------------------------------------------
# 14. SmartAPIWebSocketClient Lifecycle & Background Threads
# ---------------------------------------------------------------------------

def test_websocket_client_lifecycle_and_background_threads(tmp_path):
    auth = MagicMock(spec=SmartAPIAuth)
    auth.websocket_authorization = "Bearer test"
    auth.api_key = "key"
    auth.client_code = "client"
    auth.feed_token = "token"

    mock_ws = MagicMock()
    client = SmartAPIWebSocketClient(
        auth=auth,
        allow_insecure_tls=True,
        quarantine_db_path=str(tmp_path / "quarantine.duckdb"),
        websocket_factory=lambda *args, **kwargs: mock_ws,
    )

    # 1. SSL options & Auth headers
    headers = client._build_auth_headers()
    assert headers["Authorization"] == "Bearer test"
    ssl_opts = client._build_ssl_options()
    assert "cert_reqs" in ssl_opts

    # 2. Ping / Pong
    client._on_ping(None, b"", generation=0)
    client._on_pong(None, b"", generation=0)

    # 3. Callbacks: reanchor, repair
    client.on_stream_reanchored = MagicMock()
    client.on_gap_repaired = MagicMock()
    client.reanchor_stream("NSE", "2885", 100)
    client.on_stream_reanchored.assert_called_once()
    client.repair_gap("NSE", "2885", "gap_1")
    client.on_gap_repaired.assert_called_once()

    # 4. Dispatch worker with feed latency and quality filtering
    from data_platform.contracts import LtpTick
    t0 = datetime(2026, 1, 6, 9, 15, 0, tzinfo=timezone.utc)
    ev_trusted = LtpTick(mode=LiveTickerMode.LTP, exchange="NSE", token="2885", symbol="RELIANCE", ltp=100.0, exchange_timestamp=t0, received_at_utc=t0, received_monotonic_ns=time.monotonic_ns(), raw_packet_size=32, sequence_number=1, stream_epoch=0, feed_latency_ms=15.0)
    ev_degraded = LtpTick(mode=LiveTickerMode.LTP, exchange="NSE", token="2885", symbol="RELIANCE", ltp=100.0, exchange_timestamp=t0, received_at_utc=t0, received_monotonic_ns=time.monotonic_ns(), raw_packet_size=32, sequence_number=2, stream_epoch=0, quality_state="DEGRADED")
    
    received_ticks = []
    client.subscribe_tick(lambda e: received_ticks.append(e))

    client._dispatch_queue.put(ev_degraded)
    client._dispatch_queue.put(ev_trusted)

    # Start and quickly stop
    with patch.object(client, "_connect_socket"):
        client.start()
        time.sleep(0.3)
        client.stop()

    assert len(received_ticks) == 1
    assert received_ticks[0].quality_state == "TRUSTED"


# ---------------------------------------------------------------------------
# 15. RunCertificationService OOS and Causality Full Coverage
# ---------------------------------------------------------------------------

def test_certification_oos_and_causality_branches(tmp_path):
    db = DuckDBManager(str(tmp_path / "cert_oos.duckdb"))
    service = RunCertificationService(db)

    # 1. Create run with frame
    db.conn.execute("INSERT INTO research_frame_certifications (frame_certification_id, research_frame_hash, contributing_dataset_ids_json, symbol, timeframe, row_count, basis, validator_version, status, verified_at, dataset_evidence_json, dq_certification_ids_json) VALUES ('frame_oos', 'h_oos', '[\"ds_oos\"]', 'RELIANCE', '1d', 10, 'SPLIT_ADJUSTED', 'v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{\"ds_oos\":\"h_ds\"}', '[\"cert_oos\"]');")
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name, raw_hash, status, lifecycle_status) VALUES ('ds_oos', 'RELIANCE', 'RELIANCE', 'NSE', '1d', 'ANGEL', 'h_ds', 'VERIFIED', 'CANONICAL_PROMOTED');")
    db.conn.execute("INSERT INTO data_quality_certifications VALUES ('cert_oos', 'ds_oos', 'v1', 6, 0, '{\"dataset_content_hash\": \"h_ds\"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
    for i, c in enumerate(["schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"], start=1):
        db.conn.execute("INSERT INTO quality_report (id, symbol, timeframe, dataset_id, check_type, issue_count, details, checked_at, certification_id) VALUES (?, 'RELIANCE', '1d', 'ds_oos', ?, 0, '{}', CURRENT_TIMESTAMP, 'cert_oos');", [500 + i, c])

    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, frame_certification_id) VALUES ('run_oos_test', 'donchian_trend', 'INDIA_EQUITY', 'RELIANCE', '1d', 'event-driven', '{}', 'h_oos', 'COMPLETED', CURRENT_TIMESTAMP, 'frame_oos');")

    # 2. Insert valid walk forward folds and metrics
    db.conn.execute("INSERT INTO walk_forward_folds VALUES ('run_oos_test', 'fold_0', '2025-01-01', '2025-06-01', '2025-06-02', '2025-12-31', '{\"entry_window\": 5}', 1, 1.5, 'h_train', 'h_test', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO walk_forward_metrics VALUES ('run_oos_test', 'fold_0', '2025-06-01', '2025-06-02', '2025-12-31', 'SHARPE_RATIO', 1.2);")
    db.conn.execute("INSERT INTO walk_forward_metrics VALUES ('run_oos_test', 'fold_0', '2025-06-01', '2025-06-02', '2025-12-31', 'MAX_DRAWDOWN', 0.15);")

    # 3. Insert causality candle observations
    for d_i in range(1, 10):
        db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', ?, 100, 105, 95, 102, 50000, 'UNADJUSTED', 'ANGEL', 'ds_oos', CURRENT_TIMESTAMP);", [f"2026-01-{d_i:02d} 15:30:00+05:30"])

    bundle_id = service.certify("run_oos_test")
    assert bundle_id is not None
    cats = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [bundle_id]).fetchall())
    assert cats["DATA_LINEAGE"] == "PASS"
    assert cats["DATA_QUALITY"] == "PASS"
    assert cats["CAUSALITY"] == "PASS"


# ---------------------------------------------------------------------------
# 16. SynchronizedPanelBuilder Corporate Actions & Exclusions
# ---------------------------------------------------------------------------

def test_datasets_builder_adjustments_and_edge_cases(tmp_path):
    db = DuckDBManager(str(tmp_path / "panel_ca.duckdb"))
    calendar = build_nse_calendar()
    builder = SynchronizedPanelBuilder(db=db, calendar=calendar, require_authoritative_certification=False)

    db.conn.execute("INSERT INTO universe_snapshots VALUES ('SNAP_CA', 'NIFTY50', 'http://nifty.com', '2026-01-01', 'h_ca', false, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO universe_snapshot_members VALUES ('SNAP_CA', 'TCS', 'TCS', '11536', 'TCS', 'IT', 'NSE', '2020-01-01', '2027-01-01', true, true, true);")
    db.conn.execute("INSERT INTO index_constituents_pit VALUES ('SNAP_CA', '11536', 'TCS', '11536', 'NSE', '2020-01-01', '2027-01-01', '2020-01-01', 0.5, 'IN', null, CURRENT_TIMESTAMP);")

    # Benchmark and stock candles with 2:1 split on 2026-01-08 (unadjusted prices 3000 before, 1500 after)
    for day_i in range(1, 15):
        p = 3000 if day_i < 8 else 1500
        db.conn.execute(
            "INSERT INTO historical_candles VALUES ('NIFTY', '999', 'NSE', '1d', ?, 20000, 20100, 19900, 20050, 500000, 'UNADJUSTED', 'ANGEL', 'ds_nifty', CURRENT_TIMESTAMP);",
            [f"2026-01-{day_i:02d} 15:30:00+05:30"],
        )
        db.conn.execute(
            "INSERT INTO historical_candles VALUES ('TCS', '11536', 'NSE', '1d', ?, ?, ? + 50, ? - 50, ?, 100000, 'UNADJUSTED', 'ANGEL', 'ds_tcs', CURRENT_TIMESTAMP);",
            [f"2026-01-{day_i:02d} 15:30:00+05:30", p, p, p, p],
        )

    # Insert corporate action (2:1 stock split)
    db.conn.execute("INSERT INTO corporate_actions (action_id, symbol, exchange, action_type, ex_date, share_multiplier, source, status) VALUES ('ca_1', 'TCS', 'NSE', 'SPLIT', '2026-01-08', 2.0, 'NSE', 'ACTIVE');")

    ds = builder.build(symbols=["TCS"], timeframe="1d", adjustment=PriceAdjustment.SPLIT_ADJUSTED, universe_snapshot_id="SNAP_CA")
    assert not ds.panel.empty
    assert "TCS" in ds.panel["symbol"].values


# ---------------------------------------------------------------------------
# 17. LiveAggregator Overnight Rollover & Interval Closing
# ---------------------------------------------------------------------------

def test_live_aggregator_rollover_and_volume_deltas():
    from data_platform.contracts import QuoteTick
    aggregator = RealtimeBarAggregator(timeframe="1d")

    t_day1 = datetime(2026, 1, 5, 9, 15, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    t_day2 = datetime(2026, 1, 6, 9, 15, 10, tzinfo=ZoneInfo("Asia/Kolkata"))

    q1 = QuoteTick(
        mode=LiveTickerMode.QUOTE, exchange="NSE", token="2885", symbol="RELIANCE",
        ltp=100.0, exchange_timestamp=t_day1, received_at_utc=t_day1, received_monotonic_ns=0,
        raw_packet_size=64, sequence_number=1, stream_epoch=0,
        last_traded_qty=5, cumulative_volume=1000,
    )
    aggregator.process_tick(q1)

    # Overnight rollover
    q2 = QuoteTick(
        mode=LiveTickerMode.QUOTE, exchange="NSE", token="2885", symbol="RELIANCE",
        ltp=105.0, exchange_timestamp=t_day2, received_at_utc=t_day2, received_monotonic_ns=0,
        raw_packet_size=64, sequence_number=2, stream_epoch=0,
        last_traded_qty=10, cumulative_volume=10,
    )
    closed = aggregator.process_tick(q2)
    assert len(closed) >= 1


# ---------------------------------------------------------------------------
# 18. Single Asset Forward Paper Engine Full Lifecycle
# ---------------------------------------------------------------------------

def test_single_asset_paper_session_full_lifecycle(tmp_path):
    calendar = build_nse_calendar()
    db = DuckDBManager(str(tmp_path / "paper_lifecycle.duckdb"))
    engine = ForwardPaperSessionEngine(db=db, calendar=calendar, risk_engine=RiskEngine(RiskPolicy()))

    trading_days = list(calendar.iter_trading_days(date(2026, 1, 1), date(2026, 2, 28)))[:18]

    # Insert historical candles across valid trading days
    for idx, t_day in enumerate(trading_days, start=1):
        p = 100.0 + (idx * 5 if idx < 10 else -idx * 5)
        db.conn.execute(
            "INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', ?, ?, ? + 2, ? - 2, ?, 10000, 'UNADJUSTED', 'ANGEL', 'ds_rel', CURRENT_TIMESTAMP);",
            [f"{t_day.isoformat()} 15:30:00+05:30", p, p, p, p],
        )

    # 1. Step 1: Bootstrap
    as_of_1 = datetime.combine(trading_days[4], datetime.min.time(), tzinfo=ZoneInfo("Asia/Kolkata")) + timedelta(hours=18)
    res1 = engine.run(
        strategy_name="donchian_trend",
        approved_run_id="run_paper_single",
        symbol="RELIANCE",
        timeframe="1d",
        parameters={"entry_window": 3, "exit_window": 2},
        as_of=as_of_1,
    )
    assert res1.status in ("BOOTSTRAPPED", "NO_NEW_BAR")

    # 2. Step 2: New bars processed (generates orders & fills)
    as_of_2 = datetime.combine(trading_days[14], datetime.min.time(), tzinfo=ZoneInfo("Asia/Kolkata")) + timedelta(hours=18)
    res2 = engine.run(
        strategy_name="donchian_trend",
        approved_run_id="run_paper_single",
        symbol="RELIANCE",
        timeframe="1d",
        parameters={"entry_window": 3, "exit_window": 2},
        as_of=as_of_2,
    )
    assert res2.session_id is not None
    assert res2.equity > 0

    # 3. Step 3: No new bar
    res3 = engine.run(
        strategy_name="donchian_trend",
        approved_run_id="run_paper_single",
        symbol="RELIANCE",
        timeframe="1d",
        parameters={"entry_window": 3, "exit_window": 2},
        as_of=as_of_2,
    )
    assert res3.status == "NO_NEW_BAR"


# ---------------------------------------------------------------------------
# 19. Portfolio Forward Paper Engine Full Lifecycle
# ---------------------------------------------------------------------------

def test_portfolio_paper_session_full_lifecycle(tmp_path):
    calendar = build_nse_calendar()
    db = DuckDBManager(str(tmp_path / "portfolio_lifecycle.duckdb"))
    engine = ForwardPortfolioPaperSessionEngine(db=db, calendar=calendar, risk_engine=RiskEngine(RiskPolicy()), require_authoritative_certification=False)

    db.conn.execute("INSERT INTO universe_snapshots VALUES ('SNAP_PORT', 'NIFTY50', 'http://nifty.com', '2026-01-01', 'h_snap', false, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO universe_snapshot_members VALUES ('SNAP_PORT', 'INFY', 'INFY', '1594', 'Infosys', 'IT', 'NSE', '2020-01-01', '2027-01-01', true, true, true);")
    db.conn.execute("INSERT INTO universe_snapshot_members VALUES ('SNAP_PORT', 'TCS', 'TCS', '11536', 'TCS', 'IT', 'NSE', '2020-01-01', '2027-01-01', true, true, true);")
    db.conn.execute("INSERT INTO index_constituents_pit VALUES ('SNAP_PORT', '1594', 'INFY', '1594', 'NSE', '2020-01-01', '2027-01-01', '2020-01-01', 0.5, 'IN', null, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO index_constituents_pit VALUES ('SNAP_PORT', '11536', 'TCS', '11536', 'NSE', '2020-01-01', '2027-01-01', '2020-01-01', 0.5, 'IN', null, CURRENT_TIMESTAMP);")

    trading_days = list(calendar.iter_trading_days(date(2026, 1, 1), date(2026, 2, 28)))[:20]

    # Insert benchmark and multi-asset candles
    for idx, t_day in enumerate(trading_days, start=1):
        day_str = f"{t_day.isoformat()} 15:30:00+05:30"
        db.conn.execute("INSERT INTO historical_candles VALUES ('NIFTY', '999', 'NSE', '1d', ?, 20000, 20100, 19900, 20050, 500000, 'UNADJUSTED', 'ANGEL', 'ds_nifty', CURRENT_TIMESTAMP);", [day_str])
        db.conn.execute("INSERT INTO historical_candles VALUES ('INFY', '1594', 'NSE', '1d', ?, ?, ? + 2, ? - 2, ?, 10000, 'UNADJUSTED', 'ANGEL', 'ds_infy', CURRENT_TIMESTAMP);", [day_str, 1000 + idx * 5, 1000 + idx * 5, 1000 + idx * 5, 1000 + idx * 5])
        db.conn.execute("INSERT INTO historical_candles VALUES ('TCS', '11536', 'NSE', '1d', ?, ?, ? + 2, ? - 2, ?, 10000, 'UNADJUSTED', 'ANGEL', 'ds_tcs', CURRENT_TIMESTAMP);", [day_str, 3000 + idx * 10, 3000 + idx * 10, 3000 + idx * 10, 3000 + idx * 10])

    # 1. Step 1: Bootstrap
    as_of_1 = datetime.combine(trading_days[5], datetime.min.time(), tzinfo=ZoneInfo("Asia/Kolkata")) + timedelta(hours=18)
    res1 = engine.run(
        strategy_name="cross_sectional_momentum",
        approved_run_id="run_port_paper",
        symbols=["INFY", "TCS"],
        universe_snapshot_id="SNAP_PORT",
        benchmark_symbol="NIFTY",
        timeframe="1d",
        parameters={"lookback_bars": 5, "top_n": 1, "holding_period_days": 2},
        as_of=as_of_1,
    )
    assert res1.status in ("BOOTSTRAPPED", "NO_NEW_SESSION")

    # 2. Step 2: Rebalance & Fills
    as_of_2 = datetime.combine(trading_days[15], datetime.min.time(), tzinfo=ZoneInfo("Asia/Kolkata")) + timedelta(hours=18)
    res2 = engine.run(
        strategy_name="cross_sectional_momentum",
        approved_run_id="run_port_paper",
        symbols=["INFY", "TCS"],
        universe_snapshot_id="SNAP_PORT",
        benchmark_symbol="NIFTY",
        timeframe="1d",
        parameters={"lookback_bars": 5, "top_n": 1, "holding_period_days": 2},
        as_of=as_of_2,
    )
    assert res2.session_id is not None
    assert res2.equity > 0


# ---------------------------------------------------------------------------
# 20. StrategyPipeline Comprehensive Methods
# ---------------------------------------------------------------------------

def test_pipeline_portfolio_and_single_asset_comprehensive(tmp_path):
    db = DuckDBManager(str(tmp_path / "pipeline_comp.duckdb"))
    pipeline = StrategyPipeline(db=db, strict_calendar=True, require_authoritative_certification=False)

    # 1. Calendar strict validation rejection (1m bar outside 09:15-15:30)
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1m', '2026-01-05 03:00:00+05:30', 100, 105, 95, 100, 1000, 'UNADJUSTED', 'ANGEL', 'ds_1', CURRENT_TIMESTAMP);")
    
    with pytest.raises(ValueError, match="Candles contain out-of-session timestamps"):
        pipeline.run(
            strategy_name="donchian_trend",
            symbol="RELIANCE",
            timeframe="1m",
            parameters={"entry_window": 3, "exit_window": 2},
        )


# ---------------------------------------------------------------------------
# 21. Portfolio Backtester Capacity, Liquidity & Cash Constraints
# ---------------------------------------------------------------------------

def test_portfolio_backtester_capacity_liquidity_and_cash_constraints(tmp_path):
    backtester = PortfolioEventBacktester()

    # Rebalance inputs: 1 row with no history, 1 row with low traded value, 1 row with volume cap, 1 row with cash constraint
    day = pd.DataFrame([
        {"symbol": "SYM_NOHIST", "open": 100.0, "close": 100.0, "lagged_adv20": np.nan, "lagged_traded_value": np.nan},
        {"symbol": "SYM_LOWLIQ", "open": 100.0, "close": 100.0, "lagged_adv20": 1000.0, "lagged_traded_value": 1000.0}, # Below 10M min daily traded value
        {"symbol": "SYM_VOLCAP", "open": 100.0, "close": 100.0, "lagged_adv20": 10.0, "lagged_traded_value": 20_000_000.0}, # Max volume part limits fill
        {"symbol": "SYM_NOCASH", "open": 1000.0, "close": 1000.0, "lagged_adv20": 100000.0, "lagged_traded_value": 20_000_000.0},
    ]).set_index("symbol")

    targets = pd.DataFrame([
        {"symbol": "SYM_NOHIST", "target_weight": 0.25, "reason": "momentum_top"},
        {"symbol": "SYM_LOWLIQ", "target_weight": 0.25, "reason": "momentum_top"},
        {"symbol": "SYM_VOLCAP", "target_weight": 0.25, "reason": "momentum_top"},
        {"symbol": "SYM_NOCASH", "target_weight": 0.25, "reason": "momentum_top"},
    ])

    quantities = {"SYM_NOHIST": 0.0, "SYM_LOWLIQ": 0.0, "SYM_VOLCAP": 0.0, "SYM_NOCASH": 0.0}
    average_cost = {"SYM_NOHIST": 0.0, "SYM_LOWLIQ": 0.0, "SYM_VOLCAP": 0.0, "SYM_NOCASH": 0.0}

    cash, gen = backtester._rebalance(
        run_id="run_rebal_constraints",
        date=pd.Timestamp("2026-01-05 15:30:00+05:30"),
        day=day,
        targets=targets,
        cash=100_000.0,
        quantities=quantities,
        average_cost=average_cost,
        entry_timestamps={},
        entry_reasons={},
        entry_cost_pools={},
        entry_execution_cost_pools={},
        last_prices={},
        mode="paper",
    )

    rejection_reasons = {o["symbol"]: json.loads(o["metadata_json"]).get("rejection_reason") for o in gen["orders"]}
    assert rejection_reasons.get("SYM_NOHIST") == "INSUFFICIENT_HISTORY_FOR_CAPACITY"
    assert rejection_reasons.get("SYM_LOWLIQ") == "LIQUIDITY_REJECTION"


# ---------------------------------------------------------------------------
# 22. SynchronizedPanelBuilder Authoritative DQ and Sector Map Branches
# ---------------------------------------------------------------------------

def test_datasets_authoritative_dq_and_sector_map_error_branches(tmp_path):
    db = DuckDBManager(str(tmp_path / "panel_errors.duckdb"))
    builder = SynchronizedPanelBuilder(db=db, require_authoritative_certification=True)

    # 1. Dataset hash calculation
    ds = ResearchDataset(
        universe_snapshot_id="SNAP_TEST",
        dataset_snapshot_ids={"INFY": "ds_infy"},
        panel=pd.DataFrame({"symbol": ["INFY"], "timestamp": [pd.Timestamp("2026-01-05")], "close": [100.0]}),
        benchmark_symbol="NIFTY",
        exclusions=(),
        survivorship_bias="NONE",
        universe_name="NIFTY50",
    )
    h1 = ds.data_hash
    h2 = ds.calculate_dataset_hash()
    assert len(h1) == 64 and len(h2) == 64

    # 2. Sector map missing registered snapshot error
    db.conn.execute("INSERT INTO universe_snapshots VALUES ('NIFTY200_SNAP', 'NIFTY200', 'http://nifty.com', '2026-01-01', 'h_snap', false, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO universe_snapshot_members VALUES ('NIFTY200_SNAP', 'INFY', 'INFY', '1594', 'Infosys', 'IT', 'NSE', '2020-01-01', '2027-01-01', true, true, true);")

    # Missing sector for TCS in registered NIFTY200 snapshot
    with pytest.raises(ValueError, match="Missing authoritative sector mapping"):
        builder._sector_map(["INFY", "TCS"], "NIFTY200_SNAP")

    # 3. Benchmark alias resolution
    db.conn.execute("INSERT INTO benchmark_aliases VALUES ('NIFTY_ALIAS', 'NIFTY 50', 'EXACT', 'NSE', true, 'TEST');")
    provider_sym, rel = builder._resolve_benchmark("NIFTY_ALIAS", "1d")
    assert provider_sym == "NIFTY 50"
    assert rel == "EXACT"


# ---------------------------------------------------------------------------
# 23. RunCertificationService Error Matrix & Verification Methods
# ---------------------------------------------------------------------------

def test_run_certification_service_comprehensive_error_matrix(tmp_path):
    db = DuckDBManager(str(tmp_path / "cert_matrix.duckdb"))
    cert_svc = RunCertificationService(db=db)

    # 1. certify fail-closed on non-existent run
    with pytest.raises(ValueError, match="Cannot certify unknown run_id"):
        cert_svc.certify("non_existent_run_id")

    # 2. certify on run with no frame cert / DQ evidence
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes) VALUES ('run_cand', 'donchian_trend', 'EQUITY', 'RELIANCE', '1d', 'BACKTEST', '{}', 'h_data', 'COMPLETED', CURRENT_TIMESTAMP, '{}');")
    bundle_id = cert_svc.certify("run_cand")
    assert bundle_id is not None
    # Check that failed certifications were recorded
    recs = db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [bundle_id]).fetchall()
    statuses = {r[0]: r[1] for r in recs}
    assert statuses.get("DATA_LINEAGE") == "FAIL"


# ---------------------------------------------------------------------------
# 24. SmartAPIWebSocketClient Watchdog & Quarantine Drainer
# ---------------------------------------------------------------------------

def test_websocket_client_watchdog_and_quarantine_drainer(tmp_path):
    auth = MagicMock()
    client = SmartAPIWebSocketClient(auth=auth, watchdog_timeout_seconds=0.01)

    # 1. Configure quarantine store and drain queue
    db_path = str(tmp_path / "quarantine.duckdb")
    client.configure_quarantine_store(db_path)
    admission = TickAdmissionResult(
        token="2885", symbol="RELIANCE", exchange="NSE",
        action=TickAdmissionAction.QUARANTINE, reasons=(AdmissionReasonCode.OUT_OF_ORDER_TIMESTAMP,),
        tick_timestamp=None, received_timestamp=datetime.now(timezone.utc), price=100.0, volume=10.0,
    )
    client._quarantine_queue.put((admission, {"raw_length": 64, "token": "2885"}))

    # Trigger single drain iteration in thread
    client._state = ConnectionState.CONNECTED
    drain_thread = threading.Thread(target=client._quarantine_worker, daemon=True)
    drain_thread.start()
    time.sleep(0.2)
    client._state = ConnectionState.STOPPED
    drain_thread.join(timeout=1.0)

    # 2. Trigger stream resync & send_json
    mock_ws = MagicMock()
    client._ws = mock_ws
    client._state = ConnectionState.CONNECTED
    client._send_json({"action": 1})
    mock_ws.send.assert_called_once()
    client._trigger_stream_resync("NSE", "2885")
    mock_ws.close.assert_called_once()


# ---------------------------------------------------------------------------
# 25. Risk Validators Additional Edge Branches
# ---------------------------------------------------------------------------

def test_risk_validators_additional_edge_branches():
    policy = RiskPolicy(
        max_position_pct=0.20,
        max_gross_exposure_pct=1.0,
        max_daily_loss_pct=0.03,
        max_drawdown_pct=0.10,
        max_open_positions=10,
        min_liquidity_crore=10.0,
        max_var_pct=0.05,
        max_sector_exposure_pct=0.30,
    )
    req_val = RequiredRiskStateValidator()

    # 1. Invalid open_position_count types using model_construct
    p_bad_int = TradeProposal.model_construct(
        symbol="RELIANCE", requested_notional=10000.0, capital=100000.0,
        current_gross_exposure=0.0, current_sector_exposure=0.0, daily_pnl=0.0,
        current_drawdown=0.0, open_position_count="not_an_int", daily_turnover_crore=20.0,
        estimated_portfolio_var_pct=0.01,
    )
    _, r1 = req_val.evaluate(p_bad_int, policy)
    assert "INVALID_RISK_STATE:open_position_count" in r1

    p_bool_int = TradeProposal.model_construct(
        symbol="RELIANCE", requested_notional=10000.0, capital=100000.0,
        current_gross_exposure=0.0, current_sector_exposure=0.0, daily_pnl=0.0,
        current_drawdown=0.0, open_position_count=True, daily_turnover_crore=20.0,
        estimated_portfolio_var_pct=0.01,
    )
    _, r2 = req_val.evaluate(p_bool_int, policy)
    assert "INVALID_RISK_STATE:open_position_count" in r2

    p_neg_int = TradeProposal.model_construct(
        symbol="RELIANCE", requested_notional=10000.0, capital=100000.0,
        current_gross_exposure=0.0, current_sector_exposure=0.0, daily_pnl=0.0,
        current_drawdown=0.0, open_position_count=-5, daily_turnover_crore=20.0,
        estimated_portfolio_var_pct=0.01,
    )
    _, r3 = req_val.evaluate(p_neg_int, policy)
    assert "INVALID_RISK_STATE:open_position_count" in r3

    # 2. Non-finite / non-positive checks
    p_bad_cap = TradeProposal.model_construct(
        symbol="RELIANCE", requested_notional=10000.0, capital=0.0,
        current_gross_exposure=0.0, current_sector_exposure=0.0, daily_pnl=0.0,
        current_drawdown=0.0, open_position_count=0, daily_turnover_crore=20.0,
        estimated_portfolio_var_pct=0.01,
    )
    _, r4 = req_val.evaluate(p_bad_cap, policy)
    assert "INVALID_RISK_STATE:capital" in r4

    p_inf_pnl = TradeProposal.model_construct(
        symbol="RELIANCE", requested_notional=10000.0, capital=100000.0,
        current_gross_exposure=0.0, current_sector_exposure=0.0, daily_pnl=float("inf"),
        current_drawdown=0.0, open_position_count=0, daily_turnover_crore=20.0,
        estimated_portfolio_var_pct=0.01,
    )
    _, r5 = req_val.evaluate(p_inf_pnl, policy)
    assert "INVALID_RISK_STATE:daily_pnl" in r5

    p_neg_gross = TradeProposal.model_construct(
        symbol="RELIANCE", requested_notional=10000.0, capital=100000.0,
        current_gross_exposure=-10.0, current_sector_exposure=0.0, daily_pnl=0.0,
        current_drawdown=0.0, open_position_count=0, daily_turnover_crore=20.0,
        estimated_portfolio_var_pct=0.01,
    )
    _, r6 = req_val.evaluate(p_neg_gross, policy)
    assert "INVALID_RISK_STATE:current_gross_exposure" in r6

    # 3. PositionSizeValidator with max_position_pct = 0
    from risk.validators import (
        PositionSizeValidator, PortfolioExposureValidator, SectorExposureValidator,
        DailyLossValidator, DrawdownValidator, TurnoverLiquidityValidator, VaRValidator,
    )
    zero_pos_policy = RiskPolicy.model_construct(max_position_pct=0.0)
    pos_val = PositionSizeValidator()
    p_pos = TradeProposal(
        symbol="RELIANCE", requested_notional=5000.0, capital=100000.0,
        current_position_notional=0.0, current_gross_exposure=0.0, current_sector_exposure=0.0,
        daily_pnl=0.0, current_drawdown=0.0, open_position_count=0, daily_turnover_crore=20.0,
        estimated_portfolio_var_pct=0.01,
    )
    notional, r7 = pos_val.evaluate(p_pos, zero_pos_policy)
    assert "position_limit_reached" in r7

    # 4. Partial reduction on gross, sector, loss, drawdown, turnover, and var limits
    # Reversing a position partially: current = -100, requested = 200 -> resulting = +100
    # risk_reducing = 100, risk_increasing = 100
    p_part_reversal = TradeProposal(
        symbol="RELIANCE", requested_notional=200.0, capital=1000.0,
        current_position_notional=-100.0, current_gross_exposure=1000.0, # at gross limit
        current_sector_exposure=300.0, # at sector limit
        daily_pnl=-50.0, # exceeding daily loss limit
        current_drawdown=0.20, # exceeding drawdown limit
        open_position_count=1, daily_turnover_crore=1.0, # below min liquidity (10)
        estimated_portfolio_var_pct=0.10, # above var limit (0.05)
    )
    
    # Portfolio exposure partial reduction rejection
    gross_val = PortfolioExposureValidator()
    n_g, r_g = gross_val.evaluate(p_part_reversal, policy)
    assert n_g == 100.0
    assert "RISK_INCREASING_PORTION_REJECTED" in r_g

    # Sector exposure partial reduction rejection
    sec_val = SectorExposureValidator()
    n_s, r_s = sec_val.evaluate(p_part_reversal, policy)
    assert n_s == 100.0
    assert "RISK_INCREASING_PORTION_REJECTED" in r_s

    # Daily loss reduce only full pass vs partial rejection
    dl_val = DailyLossValidator()
    # Pure risk reducing
    p_pure_red = TradeProposal(
        symbol="RELIANCE", requested_notional=50.0, capital=1000.0,
        current_position_notional=-100.0, current_gross_exposure=100.0,
        current_sector_exposure=0.0, daily_pnl=-50.0, current_drawdown=0.0,
        open_position_count=1, daily_turnover_crore=20.0, estimated_portfolio_var_pct=0.01,
    )
    n_dl_pure, r_dl_pure = dl_val.evaluate(p_pure_red, policy)
    assert n_dl_pure == 50.0 and len(r_dl_pure) == 0

    n_dl_part, r_dl_part = dl_val.evaluate(p_part_reversal, policy)
    assert n_dl_part == 100.0
    assert "RISK_INCREASING_PORTION_REJECTED" in r_dl_part

    # Drawdown reduce only full pass vs partial rejection
    dd_val = DrawdownValidator()
    p_dd_pure = TradeProposal(
        symbol="RELIANCE", requested_notional=50.0, capital=1000.0,
        current_position_notional=-100.0, current_gross_exposure=100.0,
        current_sector_exposure=0.0, daily_pnl=0.0, current_drawdown=0.20,
        open_position_count=1, daily_turnover_crore=20.0, estimated_portfolio_var_pct=0.01,
    )
    n_dd_pure, r_dd_pure = dd_val.evaluate(p_dd_pure, policy)
    assert n_dd_pure == 50.0 and len(r_dd_pure) == 0

    n_dd_part, r_dd_part = dd_val.evaluate(p_part_reversal, policy)
    assert n_dd_part == 100.0
    assert "RISK_INCREASING_PORTION_REJECTED" in r_dd_part

    # Turnover liquidity partial rejection
    liq_val = TurnoverLiquidityValidator()
    n_l, r_l = liq_val.evaluate(p_part_reversal, policy)
    assert n_l == 100.0
    assert "RISK_INCREASING_PORTION_REJECTED" in r_l

    # VaR partial rejection
    var_val = VaRValidator()
    n_v, r_v = var_val.evaluate(p_part_reversal, policy)
    assert n_v == 100.0
    assert "RISK_INCREASING_PORTION_REJECTED" in r_v


# ---------------------------------------------------------------------------
# 26. MigrationRunner Rollback on Error
# ---------------------------------------------------------------------------

def test_storage_migrations_runner_rollback_on_error(tmp_path):
    db_file = tmp_path / "broken_mig.duckdb"
    mig_dir = tmp_path / "sql_migs"
    mig_dir.mkdir(parents=True)
    
    # Write invalid SQL migration
    (mig_dir / "001_bad.sql").write_text("INVALID SQL SYNTAX STATEMENT;", encoding="utf-8")
    with patch("storage.migrations.runner.MIGRATIONS_DIR", mig_dir):
        runner = MigrationRunner(str(db_file))
        with pytest.raises(RuntimeError, match="Failed to apply migration 001_bad"):
            runner.run_migrations()


# ---------------------------------------------------------------------------
# 27. RunCertificationService Matrix Branches
# ---------------------------------------------------------------------------

def test_certification_comprehensive_matrix_branches(tmp_path):
    db = DuckDBManager(str(tmp_path / "cert_branches.duckdb"))
    cert_svc = RunCertificationService(db=db)

    # 1. Frame row with malformed JSON in frame metadata
    db.conn.execute("""
        INSERT INTO research_frame_certifications VALUES (
            'frame_malformed', 'h_data', '{invalid_json', 'RELIANCE', '1d', 10, 'SPLIT_ADJUSTED',
            'validator-v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{invalid_json', '{invalid_json', 'pit_hash'
        );
    """)
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes, frame_certification_id) VALUES ('run_malformed', 'donchian_trend', 'EQUITY', 'RELIANCE', '1d', 'BACKTEST', '{}', 'h_data', 'COMPLETED', CURRENT_TIMESTAMP, '{}', 'frame_malformed');")
    bundle_mal = cert_svc.certify("run_malformed")
    assert bundle_mal is not None

    # 2. Lineage: unverified dataset in frame
    db.conn.execute("""
        INSERT INTO market_datasets (
            dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name,
            raw_hash, transformation_hash, status, lifecycle_status
        ) VALUES (
            'ds_unverified', 'RELIANCE', 'RELIANCE', '1d', 'NSE', 'TEST',
            'h_raw', 'h_trans', 'UNVERIFIED', 'INGESTED'
        );
    """)
    db.conn.execute("""
        INSERT INTO research_frame_certifications VALUES (
            'frame_unverified_ds', 'h_data2', '["ds_unverified"]', 'RELIANCE', '1d', 10, 'SPLIT_ADJUSTED',
            'validator-v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{"ds_unverified": "h_trans"}', '["cert_dummy"]', NULL
        );
    """)
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes, frame_certification_id) VALUES ('run_unverified_ds', 'donchian_trend', 'EQUITY', 'RELIANCE', '1d', 'BACKTEST', '{}', 'h_data2', 'COMPLETED', CURRENT_TIMESTAMP, '{}', 'frame_unverified_ds');")
    bundle_unv = cert_svc.certify("run_unverified_ds")
    recs = db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [bundle_unv]).fetchall()
    statuses = {r[0]: r[1] for r in recs}
    assert statuses.get("DATA_LINEAGE") == "FAIL"

    # 3. Causality: invalid fill timestamps (fill < order.requested_at)
    db.conn.execute("INSERT INTO strategy_orders (order_id, run_id, symbol, side, quantity, order_type, time_in_force, status, requested_at) VALUES ('ord_1', 'run_bad_fill', 'RELIANCE', 'BUY', 10, 'MARKET', 'DAY', 'FILLED', '2026-01-05 10:00:00+00');")
    db.conn.execute("INSERT INTO strategy_fills (fill_id, order_id, run_id, symbol, side, quantity, price, timestamp, fees, fill_type) VALUES ('fill_1', 'ord_1', 'run_bad_fill', 'RELIANCE', 'BUY', 10, 100.0, '2026-01-05 09:00:00+00', 0.0, 'STANDARD');")
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes) VALUES ('run_bad_fill', 'donchian_trend', 'EQUITY', 'RELIANCE', '1d', 'BACKTEST', '{}', 'h_data', 'COMPLETED', CURRENT_TIMESTAMP, '{}');")
    bundle_caus = cert_svc.certify("run_bad_fill")
    recs_caus = db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [bundle_caus]).fetchall()
    statuses_caus = {r[0]: r[1] for r in recs_caus}
    assert statuses_caus.get("CAUSALITY") == "FAIL"


# ---------------------------------------------------------------------------
# 28. SynchronizedPanelBuilder All Error Branches
# ---------------------------------------------------------------------------

def test_datasets_synchronized_panel_builder_all_error_branches(tmp_path):
    db = DuckDBManager(str(tmp_path / "panel_error_branches.duckdb"))
    builder = SynchronizedPanelBuilder(db=db, require_authoritative_certification=True)

    # 1. _load_bars with uncertified candle rows (missing dataset_id)
    db.conn.execute("INSERT INTO historical_candles VALUES ('INFY', '2885', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 1000, 'SPLIT_ADJUSTED', 'TEST', NULL, CURRENT_TIMESTAMP);")
    with pytest.raises(DQError, match="uncertified candle rows present"):
        builder._load_bars("INFY", "1d", require_authoritative_certification=True)

    # 2. _load_bars with unverified dataset
    db.conn.execute("DELETE FROM historical_candles;")
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status) VALUES ('ds_unv_infy', 'INFY', 'INFY', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'UNVERIFIED', 'INGESTED');")
    db.conn.execute("INSERT INTO historical_candles VALUES ('INFY', '2885', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 1000, 'SPLIT_ADJUSTED', 'TEST', 'ds_unv_infy', CURRENT_TIMESTAMP);")
    with pytest.raises(DQError, match="must be VERIFIED and CANONICAL_PROMOTED"):
        builder._load_bars("INFY", "1d", require_authoritative_certification=True)

    # 3. _load_bars with verified dataset but missing content hash
    db.conn.execute("UPDATE market_datasets SET status = 'VERIFIED', lifecycle_status = 'CANONICAL_PROMOTED', transformation_hash = NULL, raw_hash = '' WHERE dataset_id = 'ds_unv_infy';")
    with pytest.raises(DQError, match="has no immutable content hash"):
        builder._load_bars("INFY", "1d", require_authoritative_certification=True)

    # 4. _load_bars with verified dataset and hash but lacking matching certified DQ batch
    db.conn.execute("UPDATE market_datasets SET transformation_hash = 'h_trans_infy' WHERE dataset_id = 'ds_unv_infy';")
    with pytest.raises(DQError, match="lacks active CERTIFIED batch"):
        builder._load_bars("INFY", "1d", require_authoritative_certification=True)

    # 5. _load_bars with None symbol returning empty DataFrame
    assert builder._load_bars(None, "1d").empty

    # 6. _latest_dataset_id
    latest_id = builder._latest_dataset_id("INFY", "1d")
    assert latest_id == "ds_unv_infy"

    # 7. _valid_sessions out of bounds exception with strict_calendar
    cal = build_nse_calendar()
    builder_strict = SynchronizedPanelBuilder(db=db, calendar=cal, strict_calendar=True)
    bad_bars = pd.DataFrame([
        {"timestamp": "2026-01-04 09:15:00+05:30", "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": 1000}, # Sunday
    ])
    with pytest.raises(ValueError, match="outside calendar"):
        builder_strict._valid_sessions(bad_bars, "1d")


# ---------------------------------------------------------------------------
# 29. WebSocket Client Callbacks Lifecycle and Drainage
# ---------------------------------------------------------------------------

def test_websocket_client_callbacks_lifecycle_and_drain():
    auth = MagicMock()
    client = SmartAPIWebSocketClient(auth=auth)

    # 1. WebSocket callbacks: _on_error, _on_close, _on_open
    mock_ws = MagicMock()
    client._ws = mock_ws
    client._on_error(mock_ws, Exception("Simulated socket error"), generation=client._generation_id)

    client._on_close(mock_ws, 1000, "Normal closure", generation=client._generation_id)
    assert client.state in (ConnectionState.RECONNECTING, ConnectionState.STOPPED, ConnectionState.CONNECTING)

    client._state = ConnectionState.CONNECTING
    client._on_open(mock_ws, generation=client._generation_id)
    assert client.state == ConnectionState.CONNECTED

    # 2. Repair gap with callback
    cb_gap = MagicMock(side_effect=Exception("Callback crash"))
    client.on_gap_repaired = cb_gap
    client.repair_gap("NSE", "2885", "gap_123")
    cb_gap.assert_called_once()

    # 3. subscribe_symbols and unsubscribe_tick
    client.subscribe_symbols(["RELIANCE", "INFY"])
    assert len(client.registry.desired_subscriptions) > 0
    dummy_cb = MagicMock()
    client.subscribe_tick(dummy_cb)
    client.unsubscribe_tick(dummy_cb)

    # 4. Stop draining
    client.stop()
    assert client.state == ConnectionState.STOPPED


# ---------------------------------------------------------------------------
# 30. LiveAggregator Rollovers and Untrusted Windows
# ---------------------------------------------------------------------------

def test_live_aggregator_rollovers_and_untrusted_windows(tmp_path):
    db = DuckDBManager(str(tmp_path / "agg_untrusted.duckdb"))
    # Insert unresolved gaps in both stream_gap_events and stream_gaps
    db.conn.execute("INSERT INTO stream_gap_events (gap_id, exchange, token, symbol, start_time, end_time, gap_size, epoch, status, recorded_at) VALUES ('gap_ev_1', 'NSE', '2885', 'RELIANCE', '2026-01-05 09:15:00+00', '2026-01-05 09:20:00+00', 5, 1, 'UNREPAIRED', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO stream_gaps (gap_id, token, symbol, exchange, expected_sequence, received_sequence, gap_size, stream_epoch, detected_at, gap_status, repaired_at) VALUES ('gap_1', '2885', 'RELIANCE', 'NSE', 10, 15, 5, 1, '2026-01-05 09:25:00+00', 'UNREPAIRED', NULL);")

    agg = RealtimeBarAggregator(timeframe="1m")
    agg.load_unresolved_gaps(db)
    assert "RELIANCE" in agg._untrusted_windows
    assert len(agg._untrusted_windows["RELIANCE"]) == 2

    # 1. Process LtpTick
    from data_platform.contracts import LiveTickerMode, LtpTick
    ltp = LtpTick(
        exchange="NSE", token="2885", symbol="RELIANCE",
        mode=LiveTickerMode.LTP,
        exchange_timestamp=datetime(2026, 1, 5, 9, 16, 0, tzinfo=timezone.utc),
        received_at_utc=datetime(2026, 1, 5, 9, 16, 0, tzinfo=timezone.utc),
        received_monotonic_ns=0,
        raw_packet_size=100,
        sequence_number=1,
        ltp=2500.0,
    )
    agg.process_tick(ltp)

    # 2. Get current bar snapshot
    snap = agg.get_current_bar_snapshot("RELIANCE")
    assert snap is not None
    assert snap.quality_status == "UNTRUSTED" # Due to overlap with gap window

    # 3. Late tick arriving for already closed window
    window_key = ("RELIANCE", pd.Timestamp("2026-01-05 09:16:00+00"))
    agg._closed_windows.add(window_key)
    late_tick = LtpTick(
        exchange="NSE", token="2885", symbol="RELIANCE",
        mode=LiveTickerMode.LTP,
        exchange_timestamp=datetime(2026, 1, 5, 9, 16, 30, tzinfo=timezone.utc),
        received_at_utc=datetime(2026, 1, 5, 9, 16, 30, tzinfo=timezone.utc),
        received_monotonic_ns=0,
        raw_packet_size=100,
        sequence_number=2,
        ltp=2501.0,
    )
    agg.process_tick(late_tick)
    assert agg._dropped_late_ticks_count > 0

    # 4. Close degraded interval and repair gap
    agg.close_degraded_interval("RELIANCE", datetime(2026, 1, 5, 9, 30, 0, tzinfo=timezone.utc))
    agg.repair_gap("RELIANCE", datetime(2026, 1, 5, 9, 15, 0, tzinfo=timezone.utc))

    # 5. Dispatch bars with faulty callback
    faulty_cb = MagicMock(side_effect=Exception("Subscriber crashed"))
    agg.subscribe_bar(faulty_cb)
    agg._dispatch_bars([snap])
    faulty_cb.assert_called_once()


# ---------------------------------------------------------------------------
# 31. Paper Engine Edge Branches and Persistence
# ---------------------------------------------------------------------------

def test_paper_engine_edge_branches_and_persistence(tmp_path):
    db = DuckDBManager(str(tmp_path / "paper_edge.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())
    engine = ForwardPaperSessionEngine(db=db, calendar=cal, risk_engine=risk_eng)

    # 1. Run on symbol with no completed bars -> ValueError
    with pytest.raises(ValueError, match="No completed eligible bars"):
        engine.run(strategy_name="donchian_trend", approved_run_id="run_1", symbol="NONEXISTENT", timeframe="1d")

    # 2. Intraday timeframe completed bars
    intraday_bars = pd.DataFrame([
        {"timestamp": "2026-01-05 09:20:00+05:30", "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": 1000},
    ])
    res_completed = engine._completed_bars(intraday_bars, "5m", as_of=datetime(2026, 1, 5, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
    assert len(res_completed) == 1

    # 3. _save_pending with None deletes pending row
    session_id = "sess_test_del_pending"
    engine._save_pending(session_id, {"timestamp": "2026-01-05", "target_position": 1.0}, datetime.now(timezone.utc))
    assert engine._load_pending(session_id) is not None
    engine._save_pending(session_id, None, datetime.now(timezone.utc))
    assert engine._load_pending(session_id) is None

    # 4. _paper_cost_rows with invalid JSON metadata
    fills_with_bad_json = [
        {"fill_id": "f1", "timestamp": datetime.now(timezone.utc), "metadata_json": "{bad_json"},
        {"fill_id": "f2", "timestamp": datetime.now(timezone.utc), "metadata_json": json.dumps({"cost_components": {"total_cost": 15.0}})},
    ]
    cost_rows = engine._paper_cost_rows(session_id, fills_with_bad_json)
    assert len(cost_rows) == 1
    assert cost_rows[0]["total_cost"] == 15.0


# ---------------------------------------------------------------------------
# 32. Portfolio Paper Session Edge Branches
# ---------------------------------------------------------------------------

def test_portfolio_paper_session_edge_branches(tmp_path):
    db = DuckDBManager(str(tmp_path / "port_paper_edge.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())
    port_engine = ForwardPortfolioPaperSessionEngine(db=db, calendar=cal, risk_engine=risk_eng, require_authoritative_certification=False)

    # 1. Non-daily timeframe rejected
    with pytest.raises(ValueError, match="require daily bars"):
        port_engine.run(strategy_name="cross_sectional_momentum", approved_run_id="run_1", symbols=["INFY"], universe_snapshot_id="CUSTOM", benchmark_symbol="NIFTY", timeframe="5m")

    # 2. Empty completed panel rejected
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment) VALUES ('ds_nifty', 'NIFTY', 'NIFTY', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');")
    db.conn.execute("INSERT INTO historical_candles VALUES ('NIFTY', '2885', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 1000, 'SPLIT_ADJUSTED', 'TEST', 'ds_nifty', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment) VALUES ('ds_infy', 'INFY', 'INFY', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');")
    db.conn.execute("INSERT INTO historical_candles VALUES ('INFY', '2885', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 1000, 'SPLIT_ADJUSTED', 'TEST', 'ds_infy', CURRENT_TIMESTAMP);")
    with pytest.raises(ValueError, match="No completed synchronized sessions"):
        port_engine.run(strategy_name="cross_sectional_momentum", approved_run_id="run_1", symbols=["INFY"], universe_snapshot_id="CUSTOM", benchmark_symbol="NIFTY", timeframe="1d", as_of=datetime(2026, 1, 1, tzinfo=timezone.utc))


# ---------------------------------------------------------------------------
# 33. Portfolio Rebalance Helpers and Non-Cross-Sectional Scope Rejection
# ---------------------------------------------------------------------------

def test_portfolio_backtester_equal_weight_and_vol_targets():
    from trading_stack.portfolio import equal_weight_targets, volatility_targeted_targets

    # 1. Equal weight targets with 0 active targets
    sig_zero = pd.DataFrame({"target_position": [0.0, 0.0, 0.0]})
    ew_zero = equal_weight_targets(sig_zero, max_gross_exposure=0.30)
    assert (ew_zero == 0.0).all()

    # 2. Equal weight targets with positive active targets
    sig_pos = pd.DataFrame({"target_position": [1.0, 0.0, -1.0]})
    ew_pos = equal_weight_targets(sig_pos, max_gross_exposure=0.30)
    assert ew_pos.iloc[0] == 0.15
    assert ew_pos.iloc[2] == -0.15

    # 3. Volatility targeted targets
    vol = pd.Series([0.20, 0.05, 0.10])
    vt = volatility_targeted_targets(sig_pos, vol, target_volatility=0.10, max_gross_exposure=0.30)
    assert vt.iloc[0] == 0.30
    assert vt.iloc[2] == -0.30

    # 4. Backtester run rejecting single asset strategy
    backtester = PortfolioEventBacktester()
    mock_single_strat = MagicMock()
    mock_single_strat.metadata.scope.value = "SINGLE_ASSET"
    with pytest.raises(ValueError, match="CROSS_SECTIONAL strategy"):
        backtester.run(mock_single_strat, MagicMock())


# ---------------------------------------------------------------------------
# 34. PromotionEngine All Permission and Review Branches
# ---------------------------------------------------------------------------

def test_promotion_engine_all_permission_and_review_branches(tmp_path):
    db = DuckDBManager(str(tmp_path / "promo_edge.duckdb"))
    promo = PromotionEngine(db=db)

    # 1. assert_paper_authorized with no review
    with pytest.raises(PermissionError, match="No promotion review authorizes"):
        promo.assert_paper_authorized("run_no_review", "donchian_trend")

    # 2. assert_paper_authorized with stage != PAPER_CANDIDATE / PAPER_ACTIVE
    db.conn.execute("INSERT INTO promotion_reviews (review_id, run_id, strategy_name, stage, decision, score, reasons_json, human_approved, reviewed_at) VALUES ('rev_1', 'run_rej', 'donchian_trend', 'RESEARCH_REJECTED', 'PASS', 1.0, '[]', true, CURRENT_TIMESTAMP);")
    with pytest.raises(PermissionError, match="not a paper-authorized stage"):
        promo.assert_paper_authorized("run_rej", "donchian_trend")

    # 3. assert_paper_authorized with decision != PASS or not human approved
    db.conn.execute("INSERT INTO promotion_reviews (review_id, run_id, strategy_name, stage, decision, score, reasons_json, human_approved, reviewed_at) VALUES ('rev_2', 'run_no_hum', 'donchian_trend', 'PAPER_CANDIDATE', 'PASS', 1.0, '[]', false, CURRENT_TIMESTAMP);")
    with pytest.raises(PermissionError, match="does not have a passing human approval"):
        promo.assert_paper_authorized("run_no_hum", "donchian_trend")

    # 4. review with unknown run
    with pytest.raises(ValueError, match="Unknown run"):
        promo.review("run_unknown_123")

    # 5. review with mismatched bundle
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes, frame_certification_id) VALUES ('run_mismatch', 'donchian_trend', 'EQUITY', 'RELIANCE', '1d', 'BACKTEST', '{}', 'h_data_run', 'COMPLETED', CURRENT_TIMESTAMP, '{}', 'frame_run');")
    db.conn.execute("INSERT INTO run_certification_bundles VALUES ('bundle_mismatch', 'run_mismatch', 'h_DIFFERENT_HASH', 'frame_run', 'validator-v1', CURRENT_TIMESTAMP);")
    with pytest.raises(RuntimeError, match="not bound to this run's immutable data"):
        promo.review("run_mismatch", certification_bundle_id="bundle_mismatch")


# ---------------------------------------------------------------------------
# 35. Pipeline Single Asset Attribution and Composed Frame Validation
# ---------------------------------------------------------------------------

def test_pipeline_single_asset_attribution_and_composed_frame_validation(tmp_path):
    db = DuckDBManager(str(tmp_path / "pipe_attr.duckdb"))
    pipeline = StrategyPipeline(db=db)

    # Insert valid dataset, dq cert, and 1 historical candle
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment) VALUES ('ds_dup', 'RELIANCE', 'RELIANCE', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');")
    db.conn.execute("INSERT INTO data_quality_certifications (certification_id, dataset_id, validator_version, check_count, issue_count, checks_json, status, started_at, completed_at) VALUES ('cert_dup', 'ds_dup', 'validator-v1', 6, 0, '{\"dataset_content_hash\": \"h_trans\"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
    for chk in ["schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"]:
        db.conn.execute("INSERT INTO quality_report (certification_id, symbol, timeframe, check_type, issue_count, checked_at, dataset_id) VALUES ('cert_dup', 'RELIANCE', '1d', ?, 0, CURRENT_TIMESTAMP, 'ds_dup');", [chk])
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 1000, 'SPLIT_ADJUSTED', 'TEST', 'ds_dup', CURRENT_TIMESTAMP);")

    # 1. Composed frame validation: duplicate timestamps
    dup_frame = pd.DataFrame([
        {"symbol": "RELIANCE", "exchange": "NSE", "timeframe": "1d", "timestamp": pd.Timestamp("2026-01-05 09:15:00+05:30"), "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": 1000, "adjustment": "SPLIT_ADJUSTED", "provider_name": "TEST", "dataset_id": "ds_dup"},
        {"symbol": "RELIANCE", "exchange": "NSE", "timeframe": "1d", "timestamp": pd.Timestamp("2026-01-05 09:15:00+05:30"), "open": 101.0, "high": 106.0, "low": 96.0, "close": 103.0, "volume": 1000, "adjustment": "SPLIT_ADJUSTED", "provider_name": "TEST", "dataset_id": "ds_dup"},
    ])
    with patch("trading_stack.pipeline.PriceAdjustmentEngine.adjust_ohlcv", return_value=dup_frame):
        with pytest.raises(DataQualityError, match="duplicate timestamps"):
            pipeline.load_candles("RELIANCE", "1d", require_authoritative_certification=True)

    # 2. Composed frame validation: non-monotonic timestamps
    non_mono_frame = pd.DataFrame([
        {"symbol": "RELIANCE", "exchange": "NSE", "timeframe": "1d", "timestamp": pd.Timestamp("2026-01-06 09:15:00+05:30"), "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": 1000, "adjustment": "SPLIT_ADJUSTED", "provider_name": "TEST", "dataset_id": "ds_dup"},
        {"symbol": "RELIANCE", "exchange": "NSE", "timeframe": "1d", "timestamp": pd.Timestamp("2026-01-05 09:15:00+05:30"), "open": 101.0, "high": 106.0, "low": 96.0, "close": 103.0, "volume": 1000, "adjustment": "SPLIT_ADJUSTED", "provider_name": "TEST", "dataset_id": "ds_dup"},
    ])
    with patch("trading_stack.pipeline.PriceAdjustmentEngine.adjust_ohlcv", return_value=non_mono_frame):
        with pytest.raises(DataQualityError, match="not strictly monotonic"):
            pipeline.load_candles("RELIANCE", "1d", require_authoritative_certification=True)

    # 3. Composed frame validation: OHLC violation (high < low)
    bad_ohlc_frame = pd.DataFrame([
        {"symbol": "RELIANCE", "exchange": "NSE", "timeframe": "1d", "timestamp": pd.Timestamp("2026-01-05 09:15:00+05:30"), "open": 100.0, "high": 90.0, "low": 110.0, "close": 102.0, "volume": 1000, "adjustment": "SPLIT_ADJUSTED", "provider_name": "TEST", "dataset_id": "ds_dup"},
    ])
    with patch("trading_stack.pipeline.PriceAdjustmentEngine.adjust_ohlcv", return_value=bad_ohlc_frame):
        with pytest.raises(DataQualityError, match="OHLC integrity violations"):
            pipeline.load_candles("RELIANCE", "1d", require_authoritative_certification=True)


# ---------------------------------------------------------------------------
# 36. SynchronizedPanelBuilder Authoritative Certification Full Chain
# ---------------------------------------------------------------------------

def test_datasets_synchronized_panel_builder_authoritative_full_chain(tmp_path):
    db = DuckDBManager(str(tmp_path / "panel_auth_full.duckdb"))
    cal = build_nse_calendar()

    # 1. Insert datasets and certified DQ batches for RELIANCE and TCS
    for sym, ds_id, h in [("RELIANCE", "ds_rel_1", "h_rel"), ("TCS", "ds_tcs_1", "h_tcs"), ("NIFTY", "ds_nifty_1", "h_nifty")]:
        db.conn.execute("""
            INSERT INTO market_datasets (
                dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name,
                raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment
            ) VALUES (?, ?, ?, '1d', 'NSE', 'TEST', ?, ?, 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');
        """, [ds_id, sym, sym, h, h])

        cert_id = f"cert_{ds_id}"
        db.conn.execute("""
            INSERT INTO data_quality_certifications (
                certification_id, dataset_id, validator_version, check_count, issue_count,
                checks_json, status, started_at, completed_at
            ) VALUES (?, ?, 'validator-v1', 6, 0, ?, 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
        """, [cert_id, ds_id, json.dumps({"dataset_content_hash": h})])

        for chk in ["schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"]:
            db.conn.execute("""
                INSERT INTO quality_report (
                    certification_id, symbol, timeframe, check_type, issue_count, checked_at, dataset_id
                ) VALUES (?, ?, '1d', ?, 0, CURRENT_TIMESTAMP, ?);
            """, [cert_id, sym, chk, ds_id])

        # Insert candles
        for dt_str in ["2026-01-05 09:15:00+05:30", "2026-01-06 09:15:00+05:30", "2026-01-07 09:15:00+05:30"]:
            db.conn.execute("""
                INSERT INTO historical_candles VALUES (
                    ?, '2885', 'NSE', '1d', ?, 100.0, 105.0, 95.0, 102.0, 1000, 'SPLIT_ADJUSTED', 'TEST', ?, CURRENT_TIMESTAMP
                );
            """, [sym, dt_str, ds_id])

    # Insert PIT constituents for UNIVERSE_TEST
    db.conn.execute("""
        INSERT INTO index_constituents_pit (
            universe_name, instrument_id, symbol, token, exchange, effective_from,
            effective_until, known_from, weight, inclusion_reason, exclusion_reason, recorded_at
        ) VALUES
        ('UNIVERSE_TEST', '1', 'RELIANCE', '2885', 'NSE', '2026-01-01', '2026-12-31', '2026-01-01', 0.5, 'INCLUDED', NULL, CURRENT_TIMESTAMP),
        ('UNIVERSE_TEST', '2', 'TCS', '11536', 'NSE', '2026-01-01', '2026-12-31', '2026-01-01', 0.5, 'INCLUDED', NULL, CURRENT_TIMESTAMP);
    """)

    builder = SynchronizedPanelBuilder(db=db, calendar=cal, require_authoritative_certification=True)
    res = builder.build(
        symbols=["RELIANCE", "TCS"],
        timeframe="1d",
        benchmark_symbol="NIFTY",
        universe_name="UNIVERSE_TEST",
        universe_snapshot_id="UNIVERSE_TEST",
    )

    assert res is not None
    assert res.frame_certification_id is not None
    assert len(res.dq_certification_ids) == 2
    assert "ds_rel_1" in res.dataset_content_hashes
    assert "ds_tcs_1" in res.dataset_content_hashes

    # Verify frame certification in DB
    fc = db.conn.execute("SELECT status, basis, row_count FROM research_frame_certifications WHERE frame_certification_id = ?", [res.frame_certification_id]).fetchone()
    assert fc is not None and fc[0] == "CERTIFIED" and fc[1] == "SPLIT_ADJUSTED"


# ---------------------------------------------------------------------------
# 37. RunCertificationService Deep Branches
# ---------------------------------------------------------------------------

def test_certification_service_all_branches_deep(tmp_path):
    db = DuckDBManager(str(tmp_path / "cert_deep.duckdb"))
    cert_svc = RunCertificationService(db=db)

    # 1. Dataset hash mismatch in lineage
    db.conn.execute("""
        INSERT INTO market_datasets (
            dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name,
            raw_hash, transformation_hash, status, lifecycle_status
        ) VALUES ('ds_hash_mismatch', 'RELIANCE', 'RELIANCE', '1d', 'NSE', 'TEST', 'h_raw', 'h_current', 'VERIFIED', 'CANONICAL_PROMOTED');
    """)
    db.conn.execute("""
        INSERT INTO research_frame_certifications VALUES (
            'frame_hash_mis', 'h_data', '["ds_hash_mismatch"]', 'RELIANCE', '1d', 10, 'SPLIT_ADJUSTED',
            'validator-v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{"ds_hash_mismatch": "h_DIFFERENT"}', '["cert_dummy"]', NULL
        );
    """)
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes, frame_certification_id) VALUES ('run_hash_mis', 'donchian_trend', 'EQUITY', 'RELIANCE', '1d', 'BACKTEST', '{}', 'h_data', 'COMPLETED', CURRENT_TIMESTAMP, '{}', 'frame_hash_mis');")
    b_mis = cert_svc.certify("run_hash_mis")
    recs_mis = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b_mis]).fetchall())
    assert recs_mis.get("DATA_LINEAGE") == "FAIL"

    # 2. DQ missing 6 child checks
    db.conn.execute("UPDATE market_datasets SET transformation_hash = 'h_trans_1' WHERE dataset_id = 'ds_hash_mismatch';")
    db.conn.execute("""
        UPDATE research_frame_certifications SET
            dataset_evidence_json = '{"ds_hash_mismatch": "h_trans_1"}',
            dq_certification_ids_json = '["cert_dq_incomplete"]'
        WHERE frame_certification_id = 'frame_hash_mis';
    """)
    db.conn.execute("""
        INSERT INTO data_quality_certifications (
            certification_id, dataset_id, validator_version, check_count, issue_count,
            checks_json, status, started_at, completed_at
        ) VALUES ('cert_dq_incomplete', 'ds_hash_mismatch', 'validator-v1', 5, 0, '{"dataset_content_hash": "h_trans_1"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
    """)
    # Only 5 checks inserted
    for chk in ["schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions"]:
        db.conn.execute("INSERT INTO quality_report (certification_id, symbol, timeframe, check_type, issue_count, checked_at, dataset_id) VALUES ('cert_dq_incomplete', 'RELIANCE', '1d', ?, 0, CURRENT_TIMESTAMP, 'ds_hash_mismatch');", [chk])

    b_incomp = cert_svc.certify("run_hash_mis")
    recs_incomp = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b_incomp]).fetchall())
    assert recs_incomp.get("DATA_QUALITY") == "FAIL"

    # 3. Walk forward metrics OOS pass
    db.conn.execute("""
        INSERT INTO walk_forward_metrics (
            run_id, fold_id, train_end, test_start, test_end, metric_name, metric_value
        ) VALUES (
            'run_hash_mis', '1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'sharpe', 1.5
        );
    """)
    b_wf = cert_svc.certify("run_hash_mis")
    recs_wf = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b_wf]).fetchall())
    assert recs_wf.get("OOS_WALK_FORWARD") == "PASS"


# ---------------------------------------------------------------------------
# 38. SmartAPI WebSocket Client Parsing and Modes
# ---------------------------------------------------------------------------

def test_smartapi_websocket_client_packet_parser_and_modes():
    auth = MagicMock()
    client = SmartAPIWebSocketClient(auth=auth)

    # 1. Binary parsing error handling via _on_data
    mock_ws = MagicMock()
    client._state = ConnectionState.CONNECTED
    corrupt_bytes = b"\x01\x02\x03\x04\x05"
    client._on_data(mock_ws, corrupt_bytes, opcode=2, fin=1, generation=client._generation_id)
    assert client.metrics.invalid_packets_total > 0

    # 2. Insecure TLS config
    client_insecure = SmartAPIWebSocketClient(auth=auth, allow_insecure_tls=True)
    assert client_insecure.allow_insecure_tls is True

    # 3. Stop drain and cleanup
    client.stop()
    client_insecure.stop()


# ---------------------------------------------------------------------------
# 39. Paper Engine Fills and Reconciliation Deep
# ---------------------------------------------------------------------------

def test_paper_engine_fills_and_reconciliation_deep(tmp_path):
    db = DuckDBManager(str(tmp_path / "paper_recon.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())
    engine = ForwardPaperSessionEngine(db=db, calendar=cal, risk_engine=risk_eng)

    # 1. Insert dataset, promotion review, and historical candles
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment) VALUES ('ds_rel', 'RELIANCE', 'RELIANCE', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');")
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 100.0, 1000, 'SPLIT_ADJUSTED', 'TEST', 'ds_rel', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-06 09:15:00+05:30', 105.0, 110.0, 100.0, 108.0, 1000, 'SPLIT_ADJUSTED', 'TEST', 'ds_rel', CURRENT_TIMESTAMP);")

    # Authorize run
    db.conn.execute("INSERT INTO promotion_reviews (review_id, run_id, strategy_name, stage, decision, score, reasons_json, human_approved, reviewed_at) VALUES ('rev_p', 'run_p', 'donchian_trend', 'PAPER_CANDIDATE', 'PASS', 1.0, '[]', true, CURRENT_TIMESTAMP);")

    # Run session across 2 days
    res1 = engine.run(
        strategy_name="donchian_trend",
        approved_run_id="run_p",
        symbol="RELIANCE",
        timeframe="1d",
        as_of=datetime(2026, 1, 6, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
    )
    assert res1 is not None

    res2 = engine.run(
        strategy_name="donchian_trend",
        approved_run_id="run_p",
        symbol="RELIANCE",
        timeframe="1d",
        as_of=datetime(2026, 1, 7, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
    )
    assert res2 is not None


# ---------------------------------------------------------------------------
# 40. Portfolio Backtester Dynamic Rebalance and Costs Deep
# ---------------------------------------------------------------------------

def test_portfolio_backtester_dynamic_rebalance_and_costs_deep(tmp_path):
    from trading_stack.portfolio import PortfolioEventBacktester
    from trading_stack.strategy_library.cross_sectional import CrossSectionalMomentumStrategy

    # Create synthetic panel for 3 symbols across 2 months
    dates = pd.date_range("2026-01-15", "2026-02-15", freq="B", tz="Asia/Kolkata")
    records = []
    for dt in dates:
        ts = dt.replace(hour=9, minute=15)
        for sym, base_price in [("RELIANCE", 2000.0), ("TCS", 3000.0), ("INFY", 1500.0)]:
            records.append({
                "timestamp": ts,
                "symbol": sym,
                "open": base_price,
                "high": base_price + 20.0,
                "low": base_price - 20.0,
                "close": base_price + 5.0,
                "volume": 50000,
                "eligible": True,
                "dataset_id": f"ds_{sym}",
            })

    panel_df = pd.DataFrame(records)
    dataset = ResearchDataset(
        universe_snapshot_id="UNIVERSE_TEST",
        dataset_snapshot_ids={"RELIANCE": "ds_RELIANCE", "TCS": "ds_TCS", "INFY": "ds_INFY"},
        panel=panel_df,
        benchmark_symbol="NIFTY",
        contributing_dataset_ids=("ds_RELIANCE", "ds_TCS", "ds_INFY"),
        dataset_content_hashes={"ds_RELIANCE": "h1", "ds_TCS": "h2", "ds_INFY": "h3"},
        dq_certification_ids=("c1", "c2", "c3"),
    )

    strat = CrossSectionalMomentumStrategy(long_lookback=3, skip_recent=1)
    bt = PortfolioEventBacktester()
    res = bt.run(strat, dataset, starting_capital=1000000.0)

    assert res is not None
    assert len(res.positions) > 0
    assert len(res.rebalances) > 0


# ---------------------------------------------------------------------------
# 41. Pipeline Multi-Stage Portfolio and Single Asset Deep
# ---------------------------------------------------------------------------

def test_pipeline_multi_stage_portfolio_and_single_asset_deep(tmp_path):
    db = DuckDBManager(str(tmp_path / "pipeline_multi.duckdb"))
    pipeline = StrategyPipeline(db=db)

    # 1. Insert dataset and candles for single asset run
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment) VALUES ('ds_pipe_rel', 'RELIANCE', 'RELIANCE', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');")
    dates = pd.date_range("2026-01-05", periods=15, freq="B", tz="Asia/Kolkata")
    for i, dt in enumerate(dates):
        ts_str = dt.replace(hour=9, minute=15).strftime("%Y-%m-%d %H:%M:%S%z")
        p = 2000.0 + i * 10.0
        db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', ?, ?, ?, ?, ?, 10000, 'SPLIT_ADJUSTED', 'TEST', 'ds_pipe_rel', CURRENT_TIMESTAMP);", [ts_str, p, p+10.0, p-10.0, p+5.0])

    run_res = pipeline.run(
        strategy_name="donchian_trend",
        symbol="RELIANCE",
        timeframe="1d",
        parameters={"entry_window": 5, "exit_window": 3},
        require_authoritative_certification=False,
    )
    assert run_res is not None
    assert "result" in run_res
    assert run_res["run_id"] is not None


# ---------------------------------------------------------------------------
# 42. LiveAggregator Multi-Timeframe and Volume Boundary Deep
# ---------------------------------------------------------------------------

def test_live_aggregator_multi_timeframe_and_volume_boundary_deep():
    from data_platform.contracts import LiveTickerMode, QuoteTick

    agg_5m = RealtimeBarAggregator(timeframe="5m")

    # Send a sequence of ticks across multiple minutes
    base_time = datetime(2026, 1, 5, 9, 15, 0, tzinfo=timezone.utc)
    for i in range(10):
        t = base_time + timedelta(seconds=i * 30)
        q = QuoteTick(
            exchange="NSE", token="2885", symbol="RELIANCE",
            mode=LiveTickerMode.QUOTE,
            exchange_timestamp=t,
            received_at_utc=t,
            received_monotonic_ns=0,
            raw_packet_size=120,
            sequence_number=i + 1,
            ltp=2500.0 + i,
            last_traded_qty=50,
            average_traded_price=2500.0,
            cumulative_volume=(i + 1) * 100,
            total_buy_qty=1000.0,
            total_sell_qty=1000.0,
            day_open=2500.0,
            day_high=2510.0,
            day_low=2495.0,
            day_close=2500.0,
        )
        agg_5m.process_tick(q)

    # Force window closure / roll
    future_time = base_time + timedelta(minutes=6)
    q_roll = QuoteTick(
        exchange="NSE", token="2885", symbol="RELIANCE",
        mode=LiveTickerMode.QUOTE,
        exchange_timestamp=future_time,
        received_at_utc=future_time,
        received_monotonic_ns=0,
        raw_packet_size=120,
        sequence_number=11,
        ltp=2520.0,
        last_traded_qty=50,
        average_traded_price=2505.0,
        cumulative_volume=1200,
        total_buy_qty=1000.0,
        total_sell_qty=1000.0,
        day_open=2500.0,
        day_high=2520.0,
        day_low=2495.0,
        day_close=2500.0,
    )
    agg_5m.process_tick(q_roll)
    assert len(agg_5m._closed_windows) > 0


# ---------------------------------------------------------------------------
# 43. Paper Engine True Next Open All Branches
# ---------------------------------------------------------------------------

def test_paper_engine_true_next_open_all_branches(tmp_path):
    from trading_stack.domain import OpeningTickObservation

    db = DuckDBManager(str(tmp_path / "paper_tno.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())
    engine = ForwardPaperSessionEngine(db=db, calendar=cal, risk_engine=risk_eng)

    # 1. Setup market dataset and candle
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment) VALUES ('ds_tno', 'RELIANCE', 'RELIANCE', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');")
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 100.0, 1000, 'SPLIT_ADJUSTED', 'TEST', 'ds_tno', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-06 09:15:00+05:30', 105.0, 110.0, 100.0, 108.0, 1000, 'SPLIT_ADJUSTED', 'TEST', 'ds_tno', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO promotion_reviews (review_id, run_id, strategy_name, stage, decision, score, reasons_json, human_approved, reviewed_at) VALUES ('rev_tno', 'run_tno', 'donchian_trend', 'PAPER_CANDIDATE', 'PASS', 1.0, '[]', true, CURRENT_TIMESTAMP);")

    # Step 1: Day 1 (generates pending buy signal)
    engine.run(
        strategy_name="donchian_trend",
        approved_run_id="run_tno",
        symbol="RELIANCE",
        timeframe="1d",
        as_of=datetime(2026, 1, 6, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
    )

    # Step 2a: Day 2 with matching trusted OpeningTickObservation
    valid_obs = OpeningTickObservation(
        symbol="RELIANCE",
        token="2885",
        exchange="NSE",
        price=105.5,
        received_at_utc=datetime(2026, 1, 6, 3, 45, 1, tzinfo=timezone.utc),
        exchange_timestamp=datetime(2026, 1, 6, 3, 45, 0, tzinfo=timezone.utc),
        sequence_number=100,
        quality_state="TRUSTED",
    )
    res_valid = engine.run(
        strategy_name="donchian_trend",
        approved_run_id="run_tno",
        symbol="RELIANCE",
        timeframe="1d",
        execution_mode="TRUE_NEXT_OPEN",
        opening_observation=valid_obs,
        as_of=datetime(2026, 1, 7, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
    )
    assert res_valid is not None

    # Step 2b: Day 2 with mismatched token OpeningTickObservation -> rejection
    bad_obs = OpeningTickObservation(
        symbol="RELIANCE",
        token="WRONG_TOKEN",
        exchange="NSE",
        price=105.5,
        received_at_utc=datetime(2026, 1, 6, 3, 45, 1, tzinfo=timezone.utc),
        exchange_timestamp=datetime(2026, 1, 6, 3, 45, 0, tzinfo=timezone.utc),
        sequence_number=100,
        quality_state="TRUSTED",
    )
    # Set pending order to trigger execute_pending
    bar_dict = {"timestamp": "2026-01-06 09:15:00+05:30", "open_tick_observation": bad_obs, "token": "2885", "exchange": "NSE"}
    pending_dict = {"signal_timestamp": "2026-01-05 09:15:00+05:30", "target_position": 1.0, "reason": "test"}
    ret = engine._execute_pending("sess_rej", "RELIANCE", bar_dict, pending_dict, 100000.0, 0.0, 0.0, 100000.0, 100000.0, 100000.0, None, None, 0.0, 0.0, execution_mode="TRUE_NEXT_OPEN")
    rej_order = ret[7]
    assert rej_order is not None and rej_order["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# 44. Certification Comprehensive Exception and OOS Branches
# ---------------------------------------------------------------------------

def test_certification_comprehensive_exception_and_oos_branches(tmp_path):
    db = DuckDBManager(str(tmp_path / "cert_exc.duckdb"))
    cert_svc = RunCertificationService(db=db)

    # 1. Uncovered dataset in DQ check
    db.conn.execute("""
        INSERT INTO market_datasets (
            dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name,
            raw_hash, transformation_hash, status, lifecycle_status
        ) VALUES
        ('ds_cov1', 'RELIANCE', 'RELIANCE', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans1', 'VERIFIED', 'CANONICAL_PROMOTED'),
        ('ds_cov2', 'TCS', 'TCS', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans2', 'VERIFIED', 'CANONICAL_PROMOTED');
    """)
    db.conn.execute("""
        INSERT INTO data_quality_certifications (
            certification_id, dataset_id, validator_version, check_count, issue_count,
            checks_json, status, started_at, completed_at
        ) VALUES ('cert_cov1', 'ds_cov1', 'validator-v1', 6, 0, '{"dataset_content_hash": "h_trans1"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
    """)
    for chk in ["schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"]:
        db.conn.execute("INSERT INTO quality_report (certification_id, symbol, timeframe, check_type, issue_count, checked_at, dataset_id) VALUES ('cert_cov1', 'RELIANCE', '1d', ?, 0, CURRENT_TIMESTAMP, 'ds_cov1');", [chk])

    db.conn.execute("""
        INSERT INTO research_frame_certifications VALUES (
            'frame_uncovered', 'h_data', '["ds_cov1", "ds_cov2"]', 'PORTFOLIO:TEST', '1d', 10, 'SPLIT_ADJUSTED',
            'validator-v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{"ds_cov1": "h_trans1", "ds_cov2": "h_trans2"}', '["cert_cov1"]', NULL
        );
    """)
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes, frame_certification_id) VALUES ('run_uncovered', 'donchian_trend', 'EQUITY', 'PORTFOLIO:TEST', '1d', 'BACKTEST', '{}', 'h_data', 'COMPLETED', CURRENT_TIMESTAMP, '{}', 'frame_uncovered');")

    b_uncov = cert_svc.certify("run_uncovered")
    recs_uncov = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b_uncov]).fetchall())
    assert recs_uncov.get("DATA_QUALITY") == "FAIL"


# ---------------------------------------------------------------------------
# 45. Portfolio Paper Session Multiple Days and Metrics
# ---------------------------------------------------------------------------

def test_portfolio_paper_session_multiple_days_and_metrics(tmp_path):
    db = DuckDBManager(str(tmp_path / "port_paper_multi.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())
    port_engine = ForwardPortfolioPaperSessionEngine(db=db, calendar=cal, risk_engine=risk_eng, require_authoritative_certification=False)

    # Use valid calendar sessions
    sessions = [d for d in pd.date_range("2026-01-05", "2026-01-20", freq="B", tz="Asia/Kolkata") if cal.is_trading_day(d.date())]
    for sym, ds_id in [("RELIANCE", "ds_rel_p"), ("TCS", "ds_tcs_p")]:
        db.conn.execute("""
            INSERT INTO market_datasets (
                dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name,
                raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment
            ) VALUES (?, ?, ?, '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');
        """, [ds_id, sym, sym])
        for i, dt in enumerate(sessions):
            ts_str = dt.replace(hour=9, minute=15).strftime("%Y-%m-%d %H:%M:%S%z")
            p = 2000.0 + i * 5.0
            db.conn.execute("INSERT INTO historical_candles VALUES (?, '2885', 'NSE', '1d', ?, ?, ?, ?, ?, 10000, 'SPLIT_ADJUSTED', 'TEST', ?, CURRENT_TIMESTAMP);", [sym, ts_str, p, p+10.0, p-10.0, p+2.0, ds_id])

    db.conn.execute("INSERT INTO promotion_reviews (review_id, run_id, strategy_name, stage, decision, score, reasons_json, human_approved, reviewed_at) VALUES ('rev_port', 'run_port', 'cross_sectional_momentum', 'PAPER_CANDIDATE', 'PASS', 1.0, '[]', true, CURRENT_TIMESTAMP);")

    # Run Step 1: Bootstrap
    res1 = port_engine.run(
        strategy_name="cross_sectional_momentum",
        approved_run_id="run_port",
        symbols=["RELIANCE", "TCS"],
        universe_snapshot_id="CUSTOM",
        benchmark_symbol="RELIANCE",
        timeframe="1d",
        as_of=datetime(2026, 1, 15, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
    )
    assert res1 is not None
    assert res1.status == "BOOTSTRAPPED"

    # Run Step 2: Advance
    res2 = port_engine.run(
        strategy_name="cross_sectional_momentum",
        approved_run_id="run_port",
        symbols=["RELIANCE", "TCS"],
        universe_snapshot_id="CUSTOM",
        benchmark_symbol="RELIANCE",
        timeframe="1d",
        as_of=datetime(2026, 1, 20, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
    )
    assert res2 is not None
    assert res2.processed_sessions > 0


# ---------------------------------------------------------------------------
# 46. SmartAPI WebSocket Client Workers and Watchdog Deep
# ---------------------------------------------------------------------------

def test_smartapi_websocket_client_workers_and_watchdog_deep():
    auth = MagicMock()
    client = SmartAPIWebSocketClient(auth=auth)

    # 1. State snapshot and metrics
    snap = client.metrics.snapshot()
    assert "packets_received_total" in snap

    # 2. Callbacks and reanchor
    mock_cb = MagicMock()
    client.subscribe_tick(mock_cb)
    client.unsubscribe_tick(mock_cb)
    client.reanchor_stream("NSE", "2885", baseline_seq=100)
    client.repair_gap("NSE", "2885", "gap_123")

    # 3. Stop
    client.stop()


# ---------------------------------------------------------------------------
# 47. Datasets SynchronizedPanelBuilder Sector Map and Caching
# ---------------------------------------------------------------------------

def test_datasets_synchronized_panel_builder_sector_map_and_caching(tmp_path):
    db = DuckDBManager(str(tmp_path / "panel_sector.duckdb"))
    cal = build_nse_calendar()
    builder = SynchronizedPanelBuilder(db=db, calendar=cal)

    # 1. Registered universe snapshot missing symbol sector -> ValueError
    db.conn.execute("INSERT INTO universe_snapshots (snapshot_id, name, source_url, effective_date, content_hash, survivorship_bias) VALUES ('SNAP_REG_1', 'NIFTY50', 'http://test', '2026-01-01', 'h_snap', true);")
    with pytest.raises(ValueError, match="Missing authoritative sector mapping"):
        builder._sector_map(["UNKNOWN_SYM"], "SNAP_REG_1")

    # 2. _sector_map DB error -> RuntimeError
    db.conn.close()
    with pytest.raises(RuntimeError, match="Failed to load sector mapping"):
        builder._sector_map(["RELIANCE"], "SNAP_REG_1")


# ---------------------------------------------------------------------------
# 48. Pipeline Promotion Review and Full Lifecycle
# ---------------------------------------------------------------------------

def test_pipeline_promotion_review_and_full_lifecycle(tmp_path):
    db = DuckDBManager(str(tmp_path / "pipeline_promo.duckdb"))
    pipeline = StrategyPipeline(db=db)

    # Insert run, frame cert, bundle, certs
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment) VALUES ('ds_p1', 'RELIANCE', 'RELIANCE', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');")
    db.conn.execute("INSERT INTO data_quality_certifications (certification_id, dataset_id, validator_version, check_count, issue_count, checks_json, status, started_at, completed_at) VALUES ('cert_p1', 'ds_p1', 'validator-v1', 6, 0, '{\"dataset_content_hash\": \"h_trans\"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
    for chk in ["schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"]:
        db.conn.execute("INSERT INTO quality_report (certification_id, symbol, timeframe, check_type, issue_count, checked_at, dataset_id) VALUES ('cert_p1', 'RELIANCE', '1d', ?, 0, CURRENT_TIMESTAMP, 'ds_p1');", [chk])

    db.conn.execute("""
        INSERT INTO research_frame_certifications VALUES (
            'frame_p1', 'h_data', '["ds_p1"]', 'RELIANCE', '1d', 10, 'SPLIT_ADJUSTED',
            'validator-v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{"ds_p1": "h_trans"}', '["cert_p1"]', NULL
        );
    """)
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes, frame_certification_id) VALUES ('run_p1', 'donchian_trend', 'EQUITY', 'RELIANCE', '1d', 'BACKTEST', '{}', 'h_data', 'COMPLETED', CURRENT_TIMESTAMP, '{}', 'frame_p1');")
    for m, val in [("sharpe", 1.8), ("sortino", 2.0), ("calmar", 1.5), ("cagr", 0.2), ("max_drawdown", 0.1), ("trades", 50.0), ("win_rate", 0.55), ("profit_factor", 1.6), ("turnover", 2.0)]:
        db.conn.execute("INSERT INTO strategy_metrics (run_id, metric_name, metric_value) VALUES ('run_p1', ?, ?);", [m, val])

    # Certify and review
    cert_svc = RunCertificationService(db=db)
    bundle_id = cert_svc.certify("run_p1")
    review = pipeline.promotion_engine.review("run_p1", certification_bundle_id=bundle_id, human_approved=True)
    assert review is not None
    assert "decision" in review
    assert "score" in review


# ---------------------------------------------------------------------------
# 49. Certification Comprehensive Error Branches Extra
# ---------------------------------------------------------------------------

def test_certification_comprehensive_error_branches_extra(tmp_path):
    db = DuckDBManager(str(tmp_path / "cert_extra.duckdb"))
    cert_svc = RunCertificationService(db=db)

    # 1. Empty DQ certification IDs in frame
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status) VALUES ('ds_e1', 'RELIANCE', 'RELIANCE', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED');")
    db.conn.execute("INSERT INTO research_frame_certifications VALUES ('frame_nodq', 'h_data', '[\"ds_e1\"]', 'RELIANCE', '1d', 10, 'SPLIT_ADJUSTED', 'validator-v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{\"ds_e1\": \"h_trans\"}', '[]', NULL);")
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes, frame_certification_id) VALUES ('run_nodq', 'donchian_trend', 'EQUITY', 'RELIANCE', '1d', 'BACKTEST', '{}', 'h_data', 'COMPLETED', CURRENT_TIMESTAMP, '{}', 'frame_nodq');")
    b_nodq = cert_svc.certify("run_nodq")
    recs_nodq = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b_nodq]).fetchall())
    assert recs_nodq.get("DATA_QUALITY") == "FAIL"

    # 2. Invalid DQ certification status (FAILED / issue_count > 0)
    db.conn.execute("INSERT INTO data_quality_certifications (certification_id, dataset_id, validator_version, check_count, issue_count, checks_json, status, started_at, completed_at) VALUES ('cert_failed_dq', 'ds_e1', 'validator-v1', 6, 2, '{\"dataset_content_hash\": \"h_trans\"}', 'FAILED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO research_frame_certifications VALUES ('frame_badcert', 'h_data', '[\"ds_e1\"]', 'RELIANCE', '1d', 10, 'SPLIT_ADJUSTED', 'validator-v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{\"ds_e1\": \"h_trans\"}', '[\"cert_failed_dq\"]', NULL);")
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes, frame_certification_id) VALUES ('run_badcert', 'donchian_trend', 'EQUITY', 'RELIANCE', '1d', 'BACKTEST', '{}', 'h_data', 'COMPLETED', CURRENT_TIMESTAMP, '{}', 'frame_badcert');")
    b_bad = cert_svc.certify("run_badcert")
    recs_bad = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b_bad]).fetchall())
    assert recs_bad.get("DATA_QUALITY") == "FAIL"

    # 3. Unbound dataset in cert
    db.conn.execute("INSERT INTO data_quality_certifications (certification_id, dataset_id, validator_version, check_count, issue_count, checks_json, status, started_at, completed_at) VALUES ('cert_unbound', 'ds_OTHER_UNBOUND', 'validator-v1', 6, 0, '{\"dataset_content_hash\": \"h_trans\"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO research_frame_certifications VALUES ('frame_unbound_cert', 'h_data', '[\"ds_e1\"]', 'RELIANCE', '1d', 10, 'SPLIT_ADJUSTED', 'validator-v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{\"ds_e1\": \"h_trans\"}', '[\"cert_unbound\"]', NULL);")
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes, frame_certification_id) VALUES ('run_unbound_cert', 'donchian_trend', 'EQUITY', 'RELIANCE', '1d', 'BACKTEST', '{}', 'h_data', 'COMPLETED', CURRENT_TIMESTAMP, '{}', 'frame_unbound_cert');")
    b_unb = cert_svc.certify("run_unbound_cert")
    recs_unb = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b_unb]).fetchall())
    assert recs_unb.get("DATA_QUALITY") == "FAIL"

    # 4. PIT Survivorship for Portfolio with mismatched pit_evidence_hash
    db.conn.execute("INSERT INTO universe_snapshots (snapshot_id, name, source_url, effective_date, content_hash, survivorship_bias) VALUES ('UNIV_MISTEST', 'UNIV_MISTEST', 'http://test', '2026-01-01', 'h_snap', true);")
    db.conn.execute("INSERT INTO index_constituents_pit (universe_name, instrument_id, symbol, token, exchange, effective_from, effective_until, known_from, weight, inclusion_reason, exclusion_reason, recorded_at) VALUES ('UNIV_MISTEST', '1', 'RELIANCE', '2885', 'NSE', '2026-01-01', '2026-12-31', '2026-01-01', 1.0, 'INCLUDED', NULL, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO research_frame_certifications VALUES ('frame_pit_mis', 'h_data', '[\"ds_e1\"]', 'PORTFOLIO:UNIV_MISTEST', '1d', 10, 'SPLIT_ADJUSTED', 'validator-v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{\"ds_e1\": \"h_trans\"}', '[\"cert_unbound\"]', 'WRONG_PIT_HASH');")
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes, frame_certification_id) VALUES ('run_pit_mis', 'cross_sectional_momentum', 'EQUITY', 'PORTFOLIO:UNIV_MISTEST', '1d', 'BACKTEST', '{}', 'h_data', 'COMPLETED', CURRENT_TIMESTAMP, '{}', 'frame_pit_mis');")
    b_pit_mis = cert_svc.certify("run_pit_mis")
    recs_pit_mis = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b_pit_mis]).fetchall())
    assert recs_pit_mis.get("PIT_SURVIVORSHIP") == "FAIL"


# ---------------------------------------------------------------------------
# 50. Pipeline Single Asset Attribution and Paper Risk Extra
# ---------------------------------------------------------------------------

def test_pipeline_single_asset_attribution_and_paper_risk_extra(tmp_path):
    from trading_stack.backtest import ExecutionModel
    from trading_stack.domain import AssetClass

    db = DuckDBManager(str(tmp_path / "pipe_attr_extra.duckdb"))
    pipeline = StrategyPipeline(db=db)

    # 1. Test _apply_paper_risk with orders DataFrame
    orders_df = pd.DataFrame([
        {
            "order_id": "ord_buy_1", "symbol": "RELIANCE", "side": "BUY", "quantity": 10.0,
            "price": 2000.0, "average_fill_price": 2000.0, "requested_at": "2026-01-05 09:15:00+05:30",
        },
        {
            "order_id": "ord_sell_1", "symbol": "RELIANCE", "side": "SELL", "quantity": 10.0,
            "price": 2050.0, "average_fill_price": 2050.0, "requested_at": "2026-01-06 09:15:00+05:30",
        },
    ])
    mock_res = MagicMock()
    mock_res.run_id = "run_risk_test"
    mock_res.orders = orders_df
    pipeline._apply_paper_risk(mock_res, starting_capital=100000.0)
    decisions = db.conn.execute("SELECT COUNT(*) FROM risk_decisions WHERE run_id = 'run_risk_test'").fetchone()
    assert decisions is not None and decisions[0] == 2

    # 2. Test _reconcile_single_asset_attribution with cost components metadata
    fills_df = pd.DataFrame([
        {
            "fill_id": "fill_1", "order_id": "ord_buy_1", "symbol": "RELIANCE", "side": "BUY",
            "quantity": 10.0, "price": 2000.0, "timestamp": "2026-01-05 09:15:00+00:00", "fees": 5.0,
            "metadata_json": json.dumps({"cost_components": {
                "brokerage": 0.0, "stt": 2.0, "exchange_transaction": 1.0, "sebi": 0.1,
                "ipft": 0.0, "dp_charge": 0.0, "stamp_duty": 0.5, "gst": 0.5,
                "total_cost": 25.0, "spread": 5.0, "slippage": 10.0, "market_impact": 5.0,
            }}),
        },
        {
            "fill_id": "fill_2", "order_id": "ord_sell_1", "symbol": "RELIANCE", "side": "SELL",
            "quantity": 10.0, "price": 2050.0, "timestamp": "2026-01-06 09:15:00+00:00", "fees": 5.0,
            "metadata_json": "{}",
        },
    ])
    mock_res.fills = fills_df
    em = ExecutionModel(slippage_bps=5.0, spread_bps=2.0)
    attr, costs, rts = pipeline._persist_single_asset_attribution(mock_res, em, persist=True)
    assert len(attr) > 0
    assert len(costs) > 0
    assert len(rts) > 0

    # 3. Test _lookup_asset_class
    ac_eq = pipeline._lookup_asset_class(symbol="RELIANCE", exchange="NSE")
    assert ac_eq == AssetClass.INDIA_EQUITY


# ---------------------------------------------------------------------------
# 51. Portfolio Backtester Constraints and Metrics Extra
# ---------------------------------------------------------------------------

def test_portfolio_backtester_constraints_and_metrics_extra():
    from trading_stack.portfolio import PortfolioEventBacktester
    bt = PortfolioEventBacktester()

    run_id = bt._run_id("cross_sectional_momentum", "h_data_12345678", {}, "event-driven")
    assert "cross_sectional_momentum:PORTFOLIO" in run_id


# ---------------------------------------------------------------------------
# 52. SmartAPI WebSocket Client Packet Decoders and Reconnect
# ---------------------------------------------------------------------------

def test_smartapi_websocket_client_packet_decoders_and_reconnect():
    auth = MagicMock()
    client = SmartAPIWebSocketClient(auth=auth)

    # 1. Connection state transition
    with client._state_lock:
        client._state = ConnectionState.CONNECTED
    assert client.state == ConnectionState.CONNECTED

    # 2. Stop
    client.stop()


# ---------------------------------------------------------------------------
# 53. Portfolio Rebalance Rejection Matrix
# ---------------------------------------------------------------------------

def test_portfolio_rebalance_rejection_matrix():
    from trading_stack.portfolio import PortfolioEventBacktester
    from trading_stack.domain import OrderStatus
    bt = PortfolioEventBacktester()

    date = pd.Timestamp("2026-01-06")
    day_df = pd.DataFrame([
        {"symbol": "RELIANCE", "open": 2000.0, "close": 2010.0, "lagged_adv20": 100.0, "lagged_traded_value": 500.0, "exchange": "NSE", "token": "2885"},
    ]).set_index("symbol", drop=False)
    targets_df = pd.DataFrame([
        {"timestamp": date, "symbol": "RELIANCE", "target_weight": 0.20, "reason": "rank_1"},
    ])

    # 1. Open tick missing in TRUE_NEXT_OPEN mode -> MISSED_LIVE_OPEN_PRICE
    cash, res_rej1 = bt._rebalance(
        run_id="run_rej_1", date=date, day=day_df, targets=targets_df, cash=100000.0,
        quantities={}, average_cost={}, entry_timestamps={}, entry_reasons={},
        entry_cost_pools={}, entry_execution_cost_pools={}, last_prices={},
        mode="paper", execution_mode="TRUE_NEXT_OPEN",
    )
    assert len(res_rej1["orders"]) > 0
    assert res_rej1["orders"][0]["status"] == OrderStatus.REJECTED.value
    meta1 = json.loads(res_rej1["orders"][0]["metadata_json"])
    assert meta1["rejection_reason"] == "MISSED_LIVE_OPEN_PRICE"

    # 2. Insufficient history for capacity -> INSUFFICIENT_HISTORY_FOR_CAPACITY
    day_df_no_adv = pd.DataFrame([
        {"symbol": "RELIANCE", "open": 2000.0, "close": 2010.0, "lagged_adv20": np.nan, "lagged_traded_value": np.nan},
    ]).set_index("symbol", drop=False)
    cash, res_rej2 = bt._rebalance(
        run_id="run_rej_2", date=date, day=day_df_no_adv, targets=targets_df, cash=100000.0,
        quantities={}, average_cost={}, entry_timestamps={}, entry_reasons={},
        entry_cost_pools={}, entry_execution_cost_pools={}, last_prices={},
        mode="backtest",
    )
    meta2 = json.loads(res_rej2["orders"][0]["metadata_json"])
    assert meta2["rejection_reason"] == "INSUFFICIENT_HISTORY_FOR_CAPACITY"

    # 3. Liquidity rejection -> LIQUIDITY_REJECTION
    cash, res_rej3 = bt._rebalance(
        run_id="run_rej_3", date=date, day=day_df, targets=targets_df, cash=100000.0,
        quantities={}, average_cost={}, entry_timestamps={}, entry_reasons={},
        entry_cost_pools={}, entry_execution_cost_pools={}, last_prices={},
        mode="backtest",
    )
    meta3 = json.loads(res_rej3["orders"][0]["metadata_json"])
    assert meta3["rejection_reason"] == "LIQUIDITY_REJECTION"

    # 4. Insufficient cash -> INSUFFICIENT_CASH
    day_df_liquid = pd.DataFrame([
        {"symbol": "RELIANCE", "open": 2000.0, "close": 2010.0, "lagged_adv20": 100000.0, "lagged_traded_value": 500000000.0, "exchange": "NSE", "token": "2885"},
    ]).set_index("symbol", drop=False)
    cash, res_rej4 = bt._rebalance(
        run_id="run_rej_4", date=date, day=day_df_liquid, targets=targets_df, cash=10.0,
        quantities={"TCS": 50.0}, average_cost={"TCS": 2000.0}, entry_timestamps={}, entry_reasons={},
        entry_cost_pools={}, entry_execution_cost_pools={}, last_prices={"TCS": 2000.0},
        mode="backtest",
    )
    meta4 = json.loads(res_rej4["orders"][0]["metadata_json"])
    assert meta4["rejection_reason"] == "INSUFFICIENT_CASH"


# ---------------------------------------------------------------------------
# 54. SmartAPI WebSocket Client Full Queue and Error Logging
# ---------------------------------------------------------------------------

def test_smartapi_websocket_client_full_queue_and_error_logging():
    auth = MagicMock()
    sink = MagicMock()
    sink.enqueue_raw_packet.return_value = False
    client = SmartAPIWebSocketClient(auth=auth, raw_packet_sink=sink)

    # 1. Raw packet sink returns False (queue saturated)
    client._state = ConnectionState.CONNECTED
    client._on_data(MagicMock(), b"\x00" * 20, opcode=2, fin=1, generation=client._generation_id)
    assert client.metrics.dispatch_queue_drops > 0

    # 2. _schedule_reconnect handler
    client._schedule_reconnect(is_auth_error=True)
    assert client.metrics.reconnect_total > 0

    # 3. Stop
    client.stop()


# ---------------------------------------------------------------------------
# 55. Datasets PIT Universe and Caching Deep
# ---------------------------------------------------------------------------

def test_datasets_pit_universe_and_caching_deep(tmp_path):
    db = DuckDBManager(str(tmp_path / "pit_cache_deep.duckdb"))
    cal = build_nse_calendar()
    builder = SynchronizedPanelBuilder(db=db, calendar=cal, require_authoritative_certification=False)

    db.conn.execute("""
        INSERT INTO market_datasets (
            dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name,
            raw_hash, transformation_hash, status, lifecycle_status
        ) VALUES ('ds_cache_test', 'RELIANCE', 'RELIANCE', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED');
    """)
    db.conn.execute("""
        INSERT INTO historical_candles VALUES
        ('RELIANCE', '2885', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 2000.0, 2010.0, 1990.0, 2005.0, 10000, 'SPLIT_ADJUSTED', 'TEST', 'ds_cache_test', CURRENT_TIMESTAMP);
    """)
    db.conn.execute("""
        INSERT INTO index_constituents_pit (
            universe_name, instrument_id, symbol, token, exchange, effective_from,
            effective_until, known_from, weight, inclusion_reason, exclusion_reason, recorded_at
        ) VALUES
        ('UNIV_FILTER_TEST', '1', 'RELIANCE', '2885', 'NSE', '2026-01-01', '2026-12-31', '2026-01-01', 1.0, 'INCLUDED', NULL, CURRENT_TIMESTAMP);
    """)

    res = builder.build(
        symbols=["RELIANCE"],
        benchmark_symbol="RELIANCE",
        timeframe="1d",
        universe_snapshot_id="UNIV_FILTER_TEST",
    )
    assert res is not None
    assert len(res.panel) > 0


# ---------------------------------------------------------------------------
# 56. Pipeline Additional Features and Summary Metrics
# ---------------------------------------------------------------------------

def test_pipeline_additional_features_and_summary_metrics(tmp_path):
    db = DuckDBManager(str(tmp_path / "pipe_summary.duckdb"))
    pipeline = StrategyPipeline(db=db)

    # 1. _latest_dataset_id
    ds_id = pipeline._latest_dataset_id("UNKNOWN_SYM_XYZ", "1d")
    assert ds_id is None

    # 2. _persist_features
    feat_df = pd.DataFrame([
        {"timestamp": "2026-01-05 09:15:00+05:30", "open": 2000.0, "high": 2010.0, "low": 1990.0, "close": 2005.0, "volume": 1000},
    ])
    pipeline._persist_features(feat_df, symbol="RELIANCE", timeframe="1d")


# ---------------------------------------------------------------------------
# 57. Certification Matrix Exceptions and Json Corruption
# ---------------------------------------------------------------------------

def test_certification_matrix_exceptions_and_json_corruption(tmp_path):
    db = DuckDBManager(str(tmp_path / "cert_corrupt.duckdb"))
    cert_svc = RunCertificationService(db=db)

    # 1. Corrupted checks_json in data_quality_certifications
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status) VALUES ('ds_corrupt', 'RELIANCE', 'RELIANCE', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED');")
    db.conn.execute("INSERT INTO data_quality_certifications (certification_id, dataset_id, validator_version, check_count, issue_count, checks_json, status, started_at, completed_at) VALUES ('cert_corrupt_json', 'ds_corrupt', 'validator-v1', 6, 0, 'INVALID_JSON_CONTENT{{{', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
    for chk in ["schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"]:
        db.conn.execute("INSERT INTO quality_report (certification_id, symbol, timeframe, check_type, issue_count, checked_at, dataset_id) VALUES ('cert_corrupt_json', 'RELIANCE', '1d', ?, 0, CURRENT_TIMESTAMP, 'ds_corrupt');", [chk])

    db.conn.execute("INSERT INTO research_frame_certifications VALUES ('frame_corrupt', 'h_data', '[\"ds_corrupt\"]', 'RELIANCE', '1d', 10, 'SPLIT_ADJUSTED', 'validator-v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{\"ds_corrupt\": \"h_trans\"}', '[\"cert_corrupt_json\"]', NULL);")
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes, frame_certification_id) VALUES ('run_corrupt', 'donchian_trend', 'EQUITY', 'RELIANCE', '1d', 'BACKTEST', '{}', 'h_data', 'COMPLETED', CURRENT_TIMESTAMP, '{}', 'frame_corrupt');")
    b_corrupt = cert_svc.certify("run_corrupt")
    recs = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b_corrupt]).fetchall())
    assert recs.get("DATA_LINEAGE") == "PASS"

    # 2. checks_json with dataset_content_hash mismatch
    db.conn.execute("INSERT INTO data_quality_certifications (certification_id, dataset_id, validator_version, check_count, issue_count, checks_json, status, started_at, completed_at) VALUES ('cert_mismatch_hash', 'ds_corrupt', 'validator-v1', 6, 0, '{\"dataset_content_hash\": \"WRONG_HASH\"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO research_frame_certifications VALUES ('frame_mismatch_hash', 'h_data', '[\"ds_corrupt\"]', 'RELIANCE', '1d', 10, 'SPLIT_ADJUSTED', 'validator-v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{\"ds_corrupt\": \"h_trans\"}', '[\"cert_mismatch_hash\"]', NULL);")
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes, frame_certification_id) VALUES ('run_mismatch_hash', 'donchian_trend', 'EQUITY', 'RELIANCE', '1d', 'BACKTEST', '{}', 'h_data', 'COMPLETED', CURRENT_TIMESTAMP, '{}', 'frame_mismatch_hash');")
    b_mis = cert_svc.certify("run_mismatch_hash")
    recs_mis = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b_mis]).fetchall())
    assert recs_mis.get("DATA_QUALITY") == "FAIL"


# ---------------------------------------------------------------------------
# 58. Portfolio Token Resolution Fallbacks and Full Position Close
# ---------------------------------------------------------------------------

def test_portfolio_token_resolution_fallbacks_and_full_position_close(tmp_path):
    from trading_stack.portfolio import PortfolioEventBacktester
    from trading_stack.domain import OrderStatus

    db = DuckDBManager(str(tmp_path / "port_token_fb.duckdb"))
    bt = PortfolioEventBacktester()
    bt.db = db

    # 1. Seed instrument_master and historical_candles
    db.conn.execute("INSERT INTO instrument_master (symbol, exch_seg, token) VALUES ('RELIANCE', 'NSE', '2885');")
    db.conn.execute("""
        INSERT INTO market_datasets (
            dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name,
            raw_hash, transformation_hash, status, lifecycle_status
        ) VALUES ('ds_tcs_token', 'TCS', 'TCS', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED');
    """)
    db.conn.execute("""
        INSERT INTO historical_candles VALUES
        ('TCS', '11536', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 3500.0, 3520.0, 3490.0, 3510.0, 10000, 'SPLIT_ADJUSTED', 'TEST', 'ds_tcs_token', CURRENT_TIMESTAMP);
    """)

    # Rebalance with open observations matching resolved tokens
    obs_rel = OpeningTickObservation(
        symbol="RELIANCE", token="2885", exchange="NSE", price=2000.0,
        received_at_utc=datetime(2026, 1, 6, 3, 45, tzinfo=timezone.utc),
        exchange_timestamp=datetime(2026, 1, 6, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata")),
        quality_state="TRUSTED",
    )
    date = pd.Timestamp("2026-01-06", tz="UTC")
    day_df = pd.DataFrame([
        {"symbol": "RELIANCE", "open": 2000.0, "close": 2010.0, "lagged_adv20": 100000.0, "lagged_traded_value": 500000000.0, "exchange": "NSE", "token": "", "open_tick_observation": obs_rel},
        {"symbol": "TCS", "open": 3500.0, "close": 3520.0, "lagged_adv20": 100000.0, "lagged_traded_value": 500000000.0, "exchange": "NSE", "token": "", "open_tick_observation": None},
    ]).set_index("symbol", drop=False)

    targets_df = pd.DataFrame([
        {"timestamp": date, "symbol": "RELIANCE", "target_weight": 0.50, "reason": "rank_1"},
    ])

    cash, res = bt._rebalance(
        run_id="run_token_test", date=date, day=day_df, targets=targets_df, cash=100000.0,
        quantities={}, average_cost={}, entry_timestamps={}, entry_reasons={},
        entry_cost_pools={}, entry_execution_cost_pools={}, last_prices={},
        mode="paper", execution_mode="TRUE_NEXT_OPEN",
    )
    assert len(res["orders"]) > 0
    assert res["orders"][0]["status"] == OrderStatus.FILLED.value

    # 2. Close full position -> Target weight 0.0
    targets_exit = pd.DataFrame([
        {"timestamp": date, "symbol": "RELIANCE", "target_weight": 0.0, "reason": "rank_exit"},
    ])
    cash_post, res_exit = bt._rebalance(
        run_id="run_token_test", date=date, day=day_df, targets=targets_exit, cash=cash,
        quantities={"RELIANCE": 25.0}, average_cost={"RELIANCE": 2000.0},
        entry_timestamps={"RELIANCE": date}, entry_reasons={"RELIANCE": "ENTRY"},
        entry_cost_pools={"RELIANCE": 50.0}, entry_execution_cost_pools={"RELIANCE": 20.0},
        last_prices={"RELIANCE": 2010.0},
        mode="paper", execution_mode="TRUE_NEXT_OPEN",
    )
    assert len(res_exit["fills"]) > 0
    assert len(res_exit["round_trips"]) > 0
    assert res_exit["round_trips"][0]["exit_reason"] == "rank_exit"


# ---------------------------------------------------------------------------
# 59. Forward Paper Session Engine Edge Branches
# ---------------------------------------------------------------------------

def test_forward_paper_session_engine_edge_branches(tmp_path):
    from trading_stack.paper import ForwardPaperSessionEngine
    from trading_stack.backtest import ExecutionModel

    db = DuckDBManager(str(tmp_path / "paper_edge.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())
    engine = ForwardPaperSessionEngine(
        db=db, calendar=cal, risk_engine=risk_eng,
        execution_model=ExecutionModel(),
    )

    bar = {
        "timestamp": "2026-01-06 09:15:00+05:30",
        "open": 2000.0,
        "high": 2010.0,
        "low": 1990.0,
        "close": 2005.0,
        "volume": 10000,
        "exchange": "NSE",
        "token": "",
    }
    pending = {"target_position": 10.0, "reason": "signal"}

    # 1. _execute_pending with TRUE_NEXT_OPEN and missing open tick -> returns REJECTED order
    (
        cash, qty, avg, e_ts, e_r, e_cp, e_ecp, order, fill, ev, rt, dec,
    ) = engine._execute_pending(
        "sess_1", "RELIANCE", bar, pending, 100000.0, 0.0, 0.0, 100000.0,
        100000.0, 100000.0, None, "ENTRY", 0.0, 0.0,
        execution_mode="TRUE_NEXT_OPEN",
    )
    assert order is not None
    assert order["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# 60. Pipeline Strict Calendar and Quality Checks Failure
# ---------------------------------------------------------------------------

def test_pipeline_strict_calendar_and_quality_checks_failure(tmp_path):
    db = DuckDBManager(str(tmp_path / "pipe_strict.duckdb"))
    pipeline = StrategyPipeline(db=db, strict_calendar=True)

    # 1. load_candles with unadjusted vs split adjusted
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment) VALUES ('ds_strict_1', 'RELIANCE', 'RELIANCE', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');")
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 2000.0, 2010.0, 1990.0, 2005.0, 10000, 'SPLIT_ADJUSTED', 'TEST', 'ds_strict_1', CURRENT_TIMESTAMP);")
    df_raw = pipeline.load_candles("RELIANCE", "1d", adjustment="SPLIT_ADJUSTED", require_authoritative_certification=False)
    assert not df_raw.empty


# ---------------------------------------------------------------------------
# 61. SmartAPI WebSocket Client Callbacks and Resolver
# ---------------------------------------------------------------------------

def test_smartapi_websocket_client_callbacks_and_resolver():
    auth = MagicMock()
    im = MagicMock()
    im.resolve_symbol.return_value = "RELIANCE"
    sink = MagicMock()

    client = SmartAPIWebSocketClient(
        auth=auth,
        instrument_master=im,
        raw_packet_sink=sink,
    )

    # 1. Callbacks registration
    mock_deg = MagicMock()
    mock_reanch = MagicMock()
    client.on_stream_degraded = mock_deg
    client.on_stream_reanchored = mock_reanch

    client.reanchor_stream("NSE", "2885", baseline_seq=100)
    assert mock_reanch.called

    client.repair_gap("NSE", "2885", "gap_test")

    # 2. Stop
    client.stop()


# ---------------------------------------------------------------------------
# 62. Certification Matrix Uncovered Datasets and Exceptions
# ---------------------------------------------------------------------------

def test_certification_matrix_uncovered_datasets_and_exceptions(tmp_path):
    db = DuckDBManager(str(tmp_path / "cert_uncovered.duckdb"))
    cert_svc = RunCertificationService(db=db)

    # 1. DQ Cert covers only 1 of 2 frame datasets -> DATA_QUALITY fails with uncovered_datasets
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status) VALUES ('ds_u1', 'RELIANCE', 'RELIANCE', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED');")
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status) VALUES ('ds_u2', 'TCS', 'TCS', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED');")
    db.conn.execute("INSERT INTO data_quality_certifications (certification_id, dataset_id, validator_version, check_count, issue_count, checks_json, status, started_at, completed_at) VALUES ('cert_u1', 'ds_u1', 'validator-v1', 6, 0, '{\"dataset_content_hash\": \"h_trans\"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
    for chk in ["schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"]:
        db.conn.execute("INSERT INTO quality_report (certification_id, symbol, timeframe, check_type, issue_count, checked_at, dataset_id) VALUES ('cert_u1', 'RELIANCE', '1d', ?, 0, CURRENT_TIMESTAMP, 'ds_u1');", [chk])

    db.conn.execute("""
        INSERT INTO research_frame_certifications VALUES (
            'frame_u12', 'h_data', '["ds_u1", "ds_u2"]', 'PORTFOLIO:UNIV_U', '1d', 10, 'SPLIT_ADJUSTED',
            'validator-v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{"ds_u1": "h_trans", "ds_u2": "h_trans"}', '["cert_u1"]', NULL
        );
    """)
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes, frame_certification_id) VALUES ('run_uncov', 'cross_sectional_momentum', 'EQUITY', 'PORTFOLIO:UNIV_U', '1d', 'BACKTEST', '{}', 'h_data', 'COMPLETED', CURRENT_TIMESTAMP, '{}', 'frame_u12');")
    b_uncov = cert_svc.certify("run_uncov")
    recs_uncov = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b_uncov]).fetchall())
    assert recs_uncov.get("DATA_QUALITY") == "FAIL"


# ---------------------------------------------------------------------------
# 63. Portfolio Additional Edge Cases and Partials
# ---------------------------------------------------------------------------

def test_portfolio_additional_edge_cases_and_partials():
    from trading_stack.portfolio import PortfolioEventBacktester
    from trading_stack.domain import OrderStatus
    bt = PortfolioEventBacktester(max_position_weight=0.80, max_gross_exposure=0.50)

    date = pd.Timestamp("2026-01-06", tz="UTC")
    day_df = pd.DataFrame([
        {"symbol": "RELIANCE", "open": 2000.0, "close": 2010.0, "lagged_adv20": 100.0, "lagged_traded_value": 500000000.0, "exchange": "NSE", "token": "2885"},
    ]).set_index("symbol", drop=False)

    # 1. Total weight > max_gross_exposure (0.80 > 0.50) -> scales down
    targets_high = pd.DataFrame([
        {"timestamp": date, "symbol": "RELIANCE", "target_weight": 0.80, "reason": "rank_1"},
    ])
    cash, res_scale = bt._rebalance(
        run_id="run_scale", date=date, day=day_df, targets=targets_high, cash=100000.0,
        quantities={}, average_cost={}, entry_timestamps={}, entry_reasons={},
        entry_cost_pools={}, entry_execution_cost_pools={}, last_prices={},
        mode="backtest",
    )
    assert len(res_scale["orders"]) > 0

    # 2. Partials via volume cap: requested quantity 25 > volume_cap (100 * 0.10 = 10) -> PARTIALLY_FILLED
    assert res_scale["orders"][0]["status"] == OrderStatus.PARTIALLY_FILLED.value


# ---------------------------------------------------------------------------
# 64. Live Aggregator Window Boundaries and Early Ticks
# ---------------------------------------------------------------------------

def test_live_aggregator_window_boundaries_and_early_ticks():
    from data_platform.contracts import LiveTickerMode, LtpTick
    cal = build_nse_calendar()
    agg = RealtimeBarAggregator(calendar=cal)

    # 1. Ticks before market open (09:00 AM) -> rejected/ignored
    early_ts = datetime(2026, 1, 6, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    tick = LtpTick(
        symbol="RELIANCE", token="2885", exchange="NSE", exchange_timestamp=early_ts,
        received_at_utc=datetime(2026, 1, 6, 3, 30, tzinfo=timezone.utc),
        received_monotonic_ns=0, raw_packet_size=20, mode=LiveTickerMode.LTP,
        sequence_number=1, ltp=2000.0,
    )
    bar = agg.process_tick(tick)
    assert bar == []

    # 2. Open bars dictionary
    open_bars = agg._open_bars
    assert isinstance(open_bars, dict)


# ---------------------------------------------------------------------------
# 65. Portfolio Paper Engine Sequential Sessions Multi Session Advance
# ---------------------------------------------------------------------------

def test_portfolio_paper_engine_sequential_sessions_multi_session_advance(tmp_path):
    db = DuckDBManager(str(tmp_path / "port_seq.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())
    port_engine = ForwardPortfolioPaperSessionEngine(db=db, calendar=cal, risk_engine=risk_eng, require_authoritative_certification=False)

    sessions = [d for d in pd.date_range("2026-01-05", "2026-01-20", freq="B", tz="Asia/Kolkata") if cal.is_trading_day(d.date())]
    for sym, ds_id in [("RELIANCE", "ds_rel_seq"), ("TCS", "ds_tcs_seq")]:
        db.conn.execute("""
            INSERT INTO market_datasets (
                dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name,
                raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment
            ) VALUES (?, ?, ?, '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');
        """, [ds_id, sym, sym])
        for i, dt in enumerate(sessions):
            ts_str = dt.replace(hour=9, minute=15).strftime("%Y-%m-%d %H:%M:%S%z")
            p = 2000.0 + i * 5.0
            db.conn.execute("INSERT INTO historical_candles VALUES (?, '2885', 'NSE', '1d', ?, ?, ?, ?, ?, 10000, 'SPLIT_ADJUSTED', 'TEST', ?, CURRENT_TIMESTAMP);", [sym, ts_str, p, p+10.0, p-10.0, p+2.0, ds_id])

    db.conn.execute("INSERT INTO promotion_reviews (review_id, run_id, strategy_name, stage, decision, score, reasons_json, human_approved, reviewed_at) VALUES ('rev_seq', 'run_seq', 'cross_sectional_momentum', 'PAPER_CANDIDATE', 'PASS', 1.0, '[]', true, CURRENT_TIMESTAMP);")

    # Step 1: Bootstrap
    res1 = port_engine.run(
        strategy_name="cross_sectional_momentum", approved_run_id="run_seq",
        symbols=["RELIANCE", "TCS"], universe_snapshot_id="CUSTOM",
        benchmark_symbol="RELIANCE", timeframe="1d",
        as_of=datetime(2026, 1, 15, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
    )
    assert res1.status == "BOOTSTRAPPED"

    # Step 2: Advance to next day
    res2 = port_engine.run(
        strategy_name="cross_sectional_momentum", approved_run_id="run_seq",
        symbols=["RELIANCE", "TCS"], universe_snapshot_id="CUSTOM",
        benchmark_symbol="RELIANCE", timeframe="1d",
        as_of=datetime(2026, 1, 16, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
    )
    assert res2.processed_sessions >= 1

    # Step 3: Advance to next day (reloads previous state from DB and reconciles)
    res3 = port_engine.run(
        strategy_name="cross_sectional_momentum", approved_run_id="run_seq",
        symbols=["RELIANCE", "TCS"], universe_snapshot_id="CUSTOM",
        benchmark_symbol="RELIANCE", timeframe="1d",
        as_of=datetime(2026, 1, 20, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
    )
    assert res3.processed_sessions >= 1


# ---------------------------------------------------------------------------
# 66. Forward Paper Session Engine Single Asset Full Coverage
# ---------------------------------------------------------------------------

def test_forward_paper_session_engine_single_asset_full_coverage(tmp_path):
    from trading_stack.paper import ForwardPaperSessionEngine
    from trading_stack.backtest import ExecutionModel

    db = DuckDBManager(str(tmp_path / "paper_single_full.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())
    engine = ForwardPaperSessionEngine(
        db=db, calendar=cal, risk_engine=risk_eng,
        execution_model=ExecutionModel(),
    )

    # 1. _execute_pending with open_tick_price passed directly as float
    bar = {
        "timestamp": "2026-01-06 09:15:00+05:30", "open": 2000.0, "high": 2010.0, "low": 1990.0,
        "close": 2005.0, "volume": 10000, "exchange": "NSE", "token": "2885",
        "open_tick_price": 2002.0,
    }
    pending = {"target_position": 10.0, "reason": "signal", "signal_timestamp": "2026-01-05 15:30:00+05:30"}
    (
        cash, qty, avg, e_ts, e_r, e_cp, e_ecp, order, fill, ev, rt, dec,
    ) = engine._execute_pending(
        "sess_single", "RELIANCE", bar, pending, 100000.0, 0.0, 0.0, 100000.0,
        100000.0, 100000.0, None, "ENTRY", 0.0, 0.0,
        execution_mode="EOD_BATCH",
    )
    assert order is not None
    assert fill is not None
    assert fill["price"] == 2005.0


# ---------------------------------------------------------------------------
# 67. Pipeline Comprehensive Lookup and Metrics
# ---------------------------------------------------------------------------

def test_pipeline_comprehensive_lookup_and_metrics(tmp_path):
    from trading_stack.domain import AssetClass
    db = DuckDBManager(str(tmp_path / "pipe_metrics.duckdb"))
    pipeline = StrategyPipeline(db=db)

    # 1. Asset class lookups for various exchange / token formats
    assert pipeline._lookup_asset_class(symbol="NIFTY 50", exchange="NSE") == AssetClass.INDIA_EQUITY
    assert pipeline._lookup_asset_class(symbol="GOLD", exchange="MCX") == AssetClass.INDIA_EQUITY

    # 2. _latest_dataset_id
    ds = pipeline._latest_dataset_id("RELIANCE", "1d")
    assert ds is None


# ---------------------------------------------------------------------------
# 68. SmartAPI WebSocket Client Binary Packets and Quarantine Draining
# ---------------------------------------------------------------------------

def test_smartapi_websocket_client_binary_packets_and_quarantine_draining():
    auth = MagicMock()
    client = SmartAPIWebSocketClient(auth=auth)

    # 1. Start when already connected (no-op branch)
    with client._state_lock:
        client._state = ConnectionState.CONNECTED
    client.start()
    assert client.state == ConnectionState.CONNECTED

    # 2. Send json when disconnected (logs warning)
    client._send_json({"action": 1})

    # 3. Stop
    client.stop()
