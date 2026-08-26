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
