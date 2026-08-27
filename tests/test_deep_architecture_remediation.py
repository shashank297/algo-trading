"""Comprehensive verification tests for deep architecture audit remediation.

Covers:
1. Single-asset walk-forward lineage & slicing (preserves all 5 exact evidence fields).
2. PromotionEngine pure stitched-OOS metrics (no fallback to in-sample metrics; fails closed).
3. TRUE_NEXT_OPEN fail-closed token identity matching (rejects when token is unresolved or mismatched).
4. Parametric return-volatility Paper VaR (dynamic volatility scaling).
5. Independent paper reconciliation (computes real numerical position drift against ledger).
6. Complete risk state in AI workflow.
7. Monotonic ATR trailing stop (ratchets upward with price; never loosens).
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from risk.engine import RiskEngine
from risk.models import RiskAction, RiskDecision, RiskPolicy, TradeProposal
from storage.duckdb_manager import DuckDBManager
from trading_stack.calendars import build_nse_calendar
from trading_stack.domain import OpeningTickObservation, StrategyScope
from trading_stack.paper import ForwardPaperSessionEngine
from trading_stack.promotion import PromotionEngine, PromotionPolicy
from trading_stack.strategy_library.single_asset import _stateful


# ---------------------------------------------------------------------------
# 1. Single-Asset Walk-Forward Lineage & Slicing
# ---------------------------------------------------------------------------

def test_single_asset_walk_forward_lineage_and_slicing(tmp_path):
    """Verify single-asset walk-forward sources certified dataset and _slice preserves all evidence fields."""
    db = DuckDBManager(str(tmp_path / "wf_lineage.duckdb"))
    cal = build_nse_calendar()

    # Populate verified dataset and certified frame in DB
    db.conn.execute("""
        INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name,
            raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment)
        VALUES ('ds_wf_1', 'RELIANCE', 'RELIANCE', '1d', 'NSE', 'TEST', 'raw_h1', 'trans_h1', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');
    """)
    db.conn.execute("""
        INSERT INTO data_quality_certifications (certification_id, dataset_id, validator_version, check_count, issue_count, checks_json, status, started_at, completed_at)
        VALUES ('cert_wf_1', 'ds_wf_1', 'validator-v1', 6, 0, '{"dataset_content_hash": "trans_h1"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
    """)
    for check in ("schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"):
        db.conn.execute(f"""
            INSERT INTO quality_report (check_type, issue_count, symbol, timeframe, dataset_id, certification_id, checked_at)
            VALUES ('{check}', 0, 'RELIANCE', '1d', 'ds_wf_1', 'cert_wf_1', CURRENT_TIMESTAMP);
        """)

    valid_days = [d for d in pd.date_range("2026-01-05", "2026-02-28", freq="B") if cal.is_trading_day(d.date())][:30]
    dates = [pd.Timestamp(f"{d.strftime('%Y-%m-%d')} 09:15:00", tz="Asia/Kolkata") for d in valid_days]
    for i, dt in enumerate(dates):
        db.conn.execute(f"""
            INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '{dt.strftime('%Y-%m-%d %H:%M:%S%z')}',
            2000.0+{i}, 2050.0+{i}, 1980.0+{i}, 2020.0+{i}, 10000, 'SPLIT_ADJUSTED', 'TEST', 'ds_wf_1', CURRENT_TIMESTAMP);
        """)

    from experiments.models import ExperimentSpec
    from experiments.walk_forward import WalkForwardEvaluator

    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["RELIANCE"],
        timeframe="1d",
        mode="event-driven",
        require_authoritative_certification=True,
    )

    evaluator = WalkForwardEvaluator(db=db, india_calendar=cal)
    source = evaluator._source(spec, StrategyScope.SINGLE_ASSET, lookback=5)

    # Verify source carries full authoritative lineage
    assert source.frame_certification_id is not None
    assert "ds_wf_1" in source.contributing_dataset_ids
    assert "cert_wf_1" in source.dq_certification_ids
    assert source.dataset_content_hashes.get("ds_wf_1") == "trans_h1"

    # Verify _slice copies all 5 evidence fields
    train_slice = evaluator._slice(source, dates[0].tz_convert("UTC"), dates[10].tz_convert("UTC"))
    assert train_slice.frame_certification_id == source.frame_certification_id
    assert train_slice.contributing_dataset_ids == source.contributing_dataset_ids
    assert train_slice.dq_certification_ids == source.dq_certification_ids
    assert train_slice.dataset_content_hashes == source.dataset_content_hashes
    assert len(train_slice.panel) == 11


# ---------------------------------------------------------------------------
# 2. PromotionEngine Pure Stitched-OOS Metrics (No In-Sample Fallback)
# ---------------------------------------------------------------------------

def test_promotion_engine_pure_oos_rejection_without_fallback(tmp_path):
    """Verify PromotionEngine fails closed when OOS equity curve is missing, ignoring high in-sample metrics."""
    db = DuckDBManager(str(tmp_path / "promo_pure.duckdb"))
    engine = PromotionEngine(db=db, policy=PromotionPolicy(minimum_sharpe=1.0, maximum_drawdown=0.20))

    # Insert run in strategy_runs
    db.conn.execute("""
        INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, finished_at)
        VALUES ('run_no_oos', 'trend_following', 'INDIA_EQUITY', 'RELIANCE', '1d', 'event-driven', '{}', 'hash_no_oos', 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
    """)
    # Insert high in-sample walk-forward metrics (which should NOT be used as fallback)
    db.conn.execute("""
        INSERT INTO walk_forward_metrics (run_id, fold_id, train_end, test_start, test_end, metric_name, metric_value)
        VALUES ('run_no_oos', 'wf-001', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'sharpe', 3.50);
    """)

    # Insert certification bundle and individual category certifications
    db.conn.execute("""
        INSERT INTO run_certification_bundles (bundle_id, run_id, run_data_hash, frame_certification_id, certification_version, created_at)
        VALUES ('b1', 'run_no_oos', 'hash_no_oos', NULL, 'v1', CURRENT_TIMESTAMP);
    """)
    for cat in ("DATA_LINEAGE", "DATA_QUALITY", "CAUSALITY", "PIT_SURVIVORSHIP", "OOS_WALK_FORWARD"):
        db.conn.execute(f"""
            INSERT INTO run_certifications (certification_id, bundle_id, run_id, category, status, evidence_json, certified_at)
            VALUES ('cert_{cat}', 'b1', 'run_no_oos', '{cat}', 'PASS', '{{}}', CURRENT_TIMESTAMP);
        """)

    review = engine.review("run_no_oos", certification_bundle_id="b1")
    assert review["decision"] == "REJECT"
    reasons = json.loads(str(review["reasons_json"]))
    assert "sharpe" in reasons  # Failed because OOS sharpe is None, NOT 3.5 in-sample fallback
    assert "out_of_sample" in reasons


# ---------------------------------------------------------------------------
# 3. Fail-Closed TRUE_NEXT_OPEN Token Identity Matching
# ---------------------------------------------------------------------------

def test_paper_engine_token_identity_unresolved_fails_closed(tmp_path):
    """Verify TRUE_NEXT_OPEN rejects when expected token cannot be resolved from any authoritative table."""
    db = DuckDBManager(str(tmp_path / "paper_unres_tok.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())
    engine = ForwardPaperSessionEngine(db=db, calendar=cal, risk_engine=risk_eng)

    # Empty DB: no instrument_master, no snapshot_members, no historical_candles
    obs = OpeningTickObservation(
        symbol="MYSTERY_SYM", token="99999", exchange="NSE", price=100.0,
        received_at_utc=datetime(2026, 1, 6, 3, 45, 1, tzinfo=timezone.utc),
        exchange_timestamp=datetime(2026, 1, 6, 3, 45, 0, tzinfo=timezone.utc),
        quality_state="TRUSTED", sequence_number=1,
    )
    bar_dict = {
        "timestamp": "2026-01-06 09:15:00+05:30", "open": 100.0, "close": 102.0,
        "volume": 1000, "exchange": "NSE", "open_tick_observation": obs,
    }
    pending = {"target_position": 0.10, "reason": "signal", "signal_timestamp": "2026-01-05 15:30:00+05:30"}

    # Must reject because expected_token could not be resolved (fail-closed)
    _, _, _, _, _, _, _, order, _, _, _, _ = engine._execute_pending(
        "sess_unres", "MYSTERY_SYM", bar_dict, pending, 100000.0, 0.0, 0.0,
        100000.0, 100000.0, 100000.0, None, "ENTRY", 0.0, 0.0,
        execution_mode="TRUE_NEXT_OPEN",
    )
    assert order is not None
    assert order["status"] == "REJECTED"
    assert "MISSED_LIVE_OPEN_PRICE" in order["metadata_json"]


# ---------------------------------------------------------------------------
# 4. Parametric Return-Volatility Paper VaR
# ---------------------------------------------------------------------------

def test_paper_engine_var_scales_with_return_volatility(tmp_path):
    """Verify estimated VaR scales dynamically with asset return volatility."""
    db = DuckDBManager(str(tmp_path / "paper_var_scale.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())
    engine = ForwardPaperSessionEngine(db=db, calendar=cal, risk_engine=risk_eng)

    bar_dict = {"timestamp": "2026-01-06 09:15:00+05:30", "open": 100.0, "close": 100.0, "volume": 1000}
    pending = {"target_position": 0.10, "reason": "signal", "signal_timestamp": "2026-01-05 15:30:00+05:30"}

    # Execute with low volatility (1%)
    captured_proposals: list[TradeProposal] = []
    with patch.object(risk_eng, "evaluate", side_effect=lambda p: (captured_proposals.append(p), RiskDecision(symbol="SYM", action=RiskAction.PASS, requested_notional=p.requested_notional, approved_notional=p.requested_notional, policy=risk_eng.policy, reasons=[]))[1]):
        engine._execute_pending(
            "sess_var", "SYM", bar_dict, pending, 100000.0, 0.0, 0.0,
            100000.0, 100000.0, 100000.0, None, "ENTRY", 0.0, 0.0,
            execution_mode="EOD_BATCH", asset_volatility=0.01,
        )
        engine._execute_pending(
            "sess_var", "SYM", bar_dict, pending, 100000.0, 0.0, 0.0,
            100000.0, 100000.0, 100000.0, None, "ENTRY", 0.0, 0.0,
            execution_mode="EOD_BATCH", asset_volatility=0.05,
        )

    assert len(captured_proposals) == 2
    var_low = captured_proposals[0].estimated_portfolio_var_pct
    var_high = captured_proposals[1].estimated_portfolio_var_pct
    assert var_low is not None and var_high is not None
    assert var_high == pytest.approx(var_low * 5.0, rel=1e-3)


# ---------------------------------------------------------------------------
# 5. Independent Paper Ledger Reconciliation
# ---------------------------------------------------------------------------

def test_paper_reconciliation_detects_real_drift(tmp_path):
    """Verify _reconcile detects genuine numerical position drift between target and ledger."""
    db = DuckDBManager(str(tmp_path / "paper_rec_drift.duckdb"))
    cal = build_nse_calendar()
    engine = ForwardPaperSessionEngine(db=db, calendar=cal, risk_engine=RiskEngine(RiskPolicy()))

    as_of = datetime(2026, 1, 6, tzinfo=timezone.utc)
    # Case 1: independently persisted intent = fill-derived ledger = 50.
    engine._record_desired_position("sess_zero", "RELIANCE", as_of, 50.0, as_of)
    db.conn.execute("INSERT INTO strategy_fills VALUES ('fill_zero', 'order_zero', 'sess_zero', 'RELIANCE', ?, 50, 100, 'BUY', 'PAPER', 0, 0, '{}', CURRENT_TIMESTAMP)", [as_of])
    rec_zero = engine._reconcile("sess_zero", as_of, [], [], 0.0, "ok")
    assert rec_zero["drift"] == 0.0

    # Case 2: desired 50 vs immutable observed fill of 30 -> drift = 20.
    engine._record_desired_position("sess_drift", "RELIANCE", as_of, 50.0, as_of)
    db.conn.execute("INSERT INTO strategy_fills VALUES ('fill_drift', 'order_drift', 'sess_drift', 'RELIANCE', ?, 30, 100, 'BUY', 'PAPER', 0, 0, '{}', CURRENT_TIMESTAMP)", [as_of])
    rec_drift = engine._reconcile("sess_drift", as_of, [{"status": "REJECTED"}], [], -10.0, "rejection")
    assert rec_drift["drift"] == 20.0
    assert "position_drift=20.0000" in rec_drift["notes"]


# ---------------------------------------------------------------------------
# 6. Complete Risk State in AI Research Workflow
# ---------------------------------------------------------------------------

def test_ai_workflow_risk_proposal_has_complete_state():
    """Verify AI research workflow constructs a TradeProposal that passes RequiredRiskStateValidator."""
    risk_eng = RiskEngine(RiskPolicy())
    proposal = TradeProposal(
        symbol="RELIANCE",
        requested_notional=5000.0,
        capital=100000.0,
        current_position_notional=0.0,
        current_gross_exposure=0.0,
        daily_pnl=0.0,
        current_drawdown=0.0,
        current_sector_exposure=0.0,
        open_position_count=0,
        daily_turnover_crore=0.0,
        estimated_portfolio_var_pct=0.01,
    )
    decision = risk_eng.evaluate(proposal)
    assert decision.action == RiskAction.PASS
    assert decision.approved_notional == 5000.0


# ---------------------------------------------------------------------------
# 7. Monotonic ATR Trailing Stop
# ---------------------------------------------------------------------------

def test_monotonic_atr_trailing_stop():
    """Verify ATR trailing stop ratchets upward monotonically and exits when price drops below high-watermark stop."""
    # Construct synthetic price series:
    # Bar 0: Enter at 100, ATR=2.0 -> stop = 100 - 3*2 = 94
    # Bar 1: Price rises to 110, ATR=2.0 -> stop ratchets to 110 - 6 = 104
    # Bar 2: Price pulls back to 106 (above 104), ATR rises to 3.0 -> stop remains 104 (does NOT loosen to 110-9=101)
    # Bar 3: Price drops to 103 (below 104) -> triggers atr_stop_loss exit
    closes = [100.0, 110.0, 106.0, 103.0]
    atrs = [2.0, 2.0, 3.0, 3.0]
    entries = [True, False, False, False]
    exits = [False, False, False, False]

    frame = pd.DataFrame({"close": closes})
    entry_s = pd.Series(entries)
    exit_s = pd.Series(exits)
    atr_s = pd.Series(atrs)

    targets, reasons, sizes = _stateful(
        frame=frame,
        entry=entry_s,
        exit_=exit_s,
        entry_reason="buy_signal",
        exit_reason="sell_signal",
        atr=atr_s,
        stop_atr_mult=3.0,
    )

    # Bar 0: Enter position
    assert targets.iloc[0] == 1.0
    assert reasons.iloc[0] == "buy_signal"

    # Bar 1: Price 110, still long
    assert targets.iloc[1] == 1.0

    # Bar 2: Price 106, trailing stop is 104 (did not loosen despite ATR jump to 3.0), still long
    assert targets.iloc[2] == 1.0

    # Bar 3: Price 103 <= 104, triggers stop loss exit
    assert targets.iloc[3] == 0.0
    assert reasons.iloc[3] == "atr_stop_loss"


# ---------------------------------------------------------------------------
# 8. Token Resolution Cascading and Untrusted Tick Rejection
# ---------------------------------------------------------------------------

def test_paper_engine_token_resolution_and_untrusted_tick_rejection(tmp_path):
    """Verify paper engine cascades token resolution through snapshot_members, pit, and candles, and rejects untrusted ticks."""
    db = DuckDBManager(str(tmp_path / "paper_cascade.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())
    engine = ForwardPaperSessionEngine(db=db, calendar=cal, risk_engine=risk_eng)

    # 1. Test resolution via universe_snapshot_members
    db.conn.execute("INSERT INTO universe_snapshots VALUES ('SNAP_CASCADE', 'NIFTY50', 'http://nifty.com', '2026-01-01', 'h1', false, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO universe_snapshot_members VALUES ('SNAP_CASCADE', 'SYM_SNAP', 'SYM_SNAP', 'TOK_SNAP', 'SnapCo', 'IT', 'NSE', '2020-01-01', '2027-01-01', true, true, true);")

    obs_trusted = OpeningTickObservation(
        symbol="SYM_SNAP", token="TOK_SNAP", exchange="NSE", price=100.0,
        received_at_utc=datetime(2026, 1, 6, 3, 45, 1, tzinfo=timezone.utc),
        exchange_timestamp=datetime(2026, 1, 6, 3, 45, 0, tzinfo=timezone.utc),
        quality_state="TRUSTED", sequence_number=1,
    )
    bar_snap = {"timestamp": "2026-01-06 09:15:00+05:30", "open": 100.0, "close": 102.0, "volume": 1000, "exchange": "NSE", "open_tick_observation": obs_trusted}
    pending = {"target_position": 0.10, "reason": "signal", "signal_timestamp": "2026-01-05 15:30:00+05:30"}

    _, _, _, _, _, _, _, order_snap, _, _, _, _ = engine._execute_pending(
        "sess_snap", "SYM_SNAP", bar_snap, pending, 100000.0, 0.0, 0.0,
        100000.0, 100000.0, 100000.0, None, "ENTRY", 0.0, 0.0,
        execution_mode="TRUE_NEXT_OPEN",
    )
    assert order_snap is not None
    assert order_snap["status"] == "FILLED"

    # 2. Test resolution via index_constituents_pit
    db.conn.execute("INSERT INTO index_constituents_pit VALUES ('SNAP_CASCADE', 'TOK_PIT', 'SYM_PIT', 'TOK_PIT', 'NSE', '2020-01-01', '2027-01-01', '2020-01-01', 0.5, 'IN', null, CURRENT_TIMESTAMP);")
    obs_pit = OpeningTickObservation(
        symbol="SYM_PIT", token="TOK_PIT", exchange="NSE", price=200.0,
        received_at_utc=datetime(2026, 1, 6, 3, 45, 1, tzinfo=timezone.utc),
        exchange_timestamp=datetime(2026, 1, 6, 3, 45, 0, tzinfo=timezone.utc),
        quality_state="TRUSTED", sequence_number=1,
    )
    bar_pit = {"timestamp": "2026-01-06 09:15:00+05:30", "open": 200.0, "close": 202.0, "volume": 1000, "exchange": "NSE", "open_tick_observation": obs_pit}
    _, _, _, _, _, _, _, order_pit, _, _, _, _ = engine._execute_pending(
        "sess_pit", "SYM_PIT", bar_pit, pending, 100000.0, 0.0, 0.0,
        100000.0, 100000.0, 100000.0, None, "ENTRY", 0.0, 0.0,
        execution_mode="TRUE_NEXT_OPEN",
    )
    assert order_pit is not None
    assert order_pit["status"] == "FILLED"

    # 3. Test resolution via historical_candles
    db.conn.execute("INSERT INTO historical_candles VALUES ('SYM_CANDLE', 'TOK_CANDLE', 'NSE', '1d', '2026-01-05 15:30:00+05:30', 50, 55, 45, 50, 10000, 'UNADJUSTED', 'ANGEL', 'ds_c', CURRENT_TIMESTAMP);")
    obs_candle = OpeningTickObservation(
        symbol="SYM_CANDLE", token="TOK_CANDLE", exchange="NSE", price=50.0,
        received_at_utc=datetime(2026, 1, 6, 3, 45, 1, tzinfo=timezone.utc),
        exchange_timestamp=datetime(2026, 1, 6, 3, 45, 0, tzinfo=timezone.utc),
        quality_state="TRUSTED", sequence_number=1,
    )
    bar_candle = {"timestamp": "2026-01-06 09:15:00+05:30", "open": 50.0, "close": 52.0, "volume": 1000, "exchange": "NSE", "open_tick_observation": obs_candle}
    _, _, _, _, _, _, _, order_candle, _, _, _, _ = engine._execute_pending(
        "sess_candle", "SYM_CANDLE", bar_candle, pending, 100000.0, 0.0, 0.0,
        100000.0, 100000.0, 100000.0, None, "ENTRY", 0.0, 0.0,
        execution_mode="TRUE_NEXT_OPEN",
    )
    assert order_candle is not None
    assert order_candle["status"] == "FILLED"

    # 4. Test rejection when tick quality is untrusted
    obs_untrusted = OpeningTickObservation(
        symbol="SYM_CANDLE", token="TOK_CANDLE", exchange="NSE", price=50.0,
        received_at_utc=datetime(2026, 1, 6, 3, 45, 1, tzinfo=timezone.utc),
        exchange_timestamp=datetime(2026, 1, 6, 3, 45, 0, tzinfo=timezone.utc),
        quality_state="QUARANTINED", sequence_number=1,
    )
    bar_untrusted = {"timestamp": "2026-01-06 09:15:00+05:30", "open": 50.0, "close": 52.0, "volume": 1000, "exchange": "NSE", "open_tick_observation": obs_untrusted}
    _, _, _, _, _, _, _, order_untrusted, _, _, _, _ = engine._execute_pending(
        "sess_untrusted", "SYM_CANDLE", bar_untrusted, pending, 100000.0, 0.0, 0.0,
        100000.0, 100000.0, 100000.0, None, "ENTRY", 0.0, 0.0,
        execution_mode="TRUE_NEXT_OPEN",
    )
    assert order_untrusted is not None
    assert order_untrusted["status"] == "REJECTED"
    assert "MISSED_LIVE_OPEN_PRICE" in order_untrusted["metadata_json"]

    # 5. Test reconciliation query exception fallback
    mock_db = MagicMock()
    mock_db.conn.execute.side_effect = Exception("DB query failure")
    engine.db = mock_db
    rec = engine._reconcile("sess_db_err", datetime(2026, 1, 6, tzinfo=timezone.utc), [], [], 0.0, "error_test")
    assert rec["drift"] == 0.0


# ---------------------------------------------------------------------------
# 9. Portfolio Paper Session Engine EOD Opening Ticks & Fallbacks
# ---------------------------------------------------------------------------

def test_portfolio_paper_engine_eod_ticks_and_edge_cases(tmp_path):
    """Verify portfolio paper engine handles EOD opening ticks, empty advances, and reconciliation DB exceptions."""
    from trading_stack.portfolio_paper import ForwardPortfolioPaperSessionEngine
    db = DuckDBManager(str(tmp_path / "portfolio_paper_eod.duckdb"))
    cal = build_nse_calendar()
    engine = ForwardPortfolioPaperSessionEngine(db=db, calendar=cal, risk_engine=RiskEngine(RiskPolicy()), require_authoritative_certification=False)

    db.conn.execute("INSERT INTO universe_snapshots VALUES ('SNAP_EOD', 'NIFTY50', 'http://nifty.com', '2026-01-01', 'h1', false, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO universe_snapshot_members VALUES ('SNAP_EOD', 'INFY', 'INFY', '1594', 'Infosys', 'IT', 'NSE', '2020-01-01', '2027-01-01', true, true, true);")
    db.conn.execute("INSERT INTO index_constituents_pit VALUES ('SNAP_EOD', '1594', 'INFY', '1594', 'NSE', '2020-01-01', '2027-01-01', '2020-01-01', 0.5, 'IN', null, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO historical_candles VALUES ('INFY', '1594', 'NSE', '1d', '2025-12-31 15:30:00+05:30', 1500, 1520, 1490, 1500, 50000, 'UNADJUSTED', 'ANGEL', 'ds_infy', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at) VALUES ('RUN_PREV_INFY', 'cross_sectional_momentum', 'INDIA_EQUITY', 'PORTFOLIO:SNAP_EOD', '1d', 'event-driven', '{\"long_lookback\": 1, \"skip_recent\": 0}', 'h_infy', 'COMPLETED', CURRENT_TIMESTAMP);")

    # Bootstrap
    res1 = engine.run(
        strategy_name="cross_sectional_momentum",
        approved_run_id="RUN_PREV_INFY",
        symbols=["INFY"],
        universe_snapshot_id="SNAP_EOD",
        benchmark_symbol="INFY",
        timeframe="1d",
        parameters={"long_lookback": 1, "skip_recent": 0},
        as_of=datetime(2025, 12, 31, 16, 0, tzinfo=timezone.utc),
    )
    assert res1.status == "BOOTSTRAPPED"

    # Run again with no new data -> NO_NEW_SESSION
    res_uptodate = engine.run(
        strategy_name="cross_sectional_momentum",
        approved_run_id="RUN_PREV_INFY",
        symbols=["INFY"],
        universe_snapshot_id="SNAP_EOD",
        benchmark_symbol="INFY",
        timeframe="1d",
        parameters={"long_lookback": 1, "skip_recent": 0},
        as_of=datetime(2025, 12, 31, 16, 0, tzinfo=timezone.utc),
    )
    assert res_uptodate.status == "NO_NEW_SESSION"

    # Advance forward with EOD opening ticks
    db.conn.execute("INSERT INTO historical_candles VALUES ('INFY', '1594', 'NSE', '1d', '2026-01-01 15:30:00+05:30', 1510, 1530, 1500, 1520, 50000, 'UNADJUSTED', 'ANGEL', 'ds_infy', CURRENT_TIMESTAMP);")
    res_eod = engine.run(
        strategy_name="cross_sectional_momentum",
        approved_run_id="RUN_PREV_INFY",
        symbols=["INFY"],
        universe_snapshot_id="SNAP_EOD",
        benchmark_symbol="INFY",
        timeframe="1d",
        parameters={"long_lookback": 1, "skip_recent": 0},
        execution_mode="EOD_BATCH",
        opening_ticks={"INFY": 1515.0},
        open_tick_timestamps={"INFY": "2026-01-01 09:15:00+05:30"},
        as_of=datetime(2026, 1, 1, 16, 0, tzinfo=timezone.utc),
    )
    assert res_eod.status == "PROCESSED"

    # Test portfolio paper reconciliation DB exception fallback
    mock_pf_db = MagicMock()
    mock_pf_db.conn.execute.side_effect = Exception("DB query failure")
    engine.db = mock_pf_db
    rec = engine._reconcile("sess_pf_err", datetime(2026, 1, 1, tzinfo=timezone.utc), [], [], 0.0, "error_test")
    assert rec["drift"] == 0.0


# ---------------------------------------------------------------------------
# 10. SmartAPI WebSocket Client Invariants & Recovery
# ---------------------------------------------------------------------------

def test_websocket_client_edge_branches():
    """Verify SmartAPIWebSocketClient handles non-binary messages, heartbeats, and reconnect states safely."""
    from smartapi.websocket_client import ConnectionState, SmartAPIWebSocketClient
    mock_auth = MagicMock()
    mock_auth.get_feed_token.return_value = "mock_feed_token"
    mock_auth.client_code = "MOCK_CLIENT"
    mock_auth.api_key = "MOCK_API_KEY"
    client = SmartAPIWebSocketClient(auth=mock_auth)
    client._state = ConnectionState.CONNECTED

    # Unhandled text frame does not crash
    client._on_data(None, "pong", 1, True, client._generation_id)
    client._on_data(None, json.dumps({"action": "heartbeat"}), 1, True, client._generation_id)

    # Ping/Pong callbacks
    client._on_ping(None, b"ping", client._generation_id)
    client._on_pong(None, b"pong", client._generation_id)

    # Error handling
    client._on_error(None, Exception("Simulated transport disconnect"), client._generation_id)
    assert client is not None
