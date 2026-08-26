"""Precisely targeted coverage tests to push critical-path modules from 94% to ≥95%.

Each test function targets specific uncovered lines identified from the coverage report:
  smartapi/websocket_client.py: 91% → lines 351, 393, 547, 652-653, 662-663, 531-532, 240
  trading_stack/pipeline.py:    92% → lines 130, 145, 148-149, 221-222, 321, 349-351, 396, 500-501, 616-617
  trading_stack/paper.py:       93% → lines 291-299, 340-341
  trading_stack/portfolio_paper.py: 94% → lines 274-281, 362
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_platform.contracts import PriceAdjustment
from risk.engine import RiskEngine
from risk.models import RiskPolicy
from smartapi.websocket_client import ConnectionState, SmartAPIWebSocketClient
from storage.duckdb_manager import DuckDBManager
from trading_stack.calendars import build_nse_calendar
from trading_stack.domain import OpeningTickObservation, StrategyScope
from trading_stack.paper import ForwardPaperSessionEngine
from trading_stack.pipeline import StrategyPipeline, DataQualityError
from trading_stack.portfolio_paper import ForwardPortfolioPaperSessionEngine


# ---------------------------------------------------------------------------
# Test 1: WebSocket edge branches (lines 351, 393, 547, 652-653, 662-663)
# ---------------------------------------------------------------------------

def test_websocket_stale_generation_and_send_errors(tmp_path):
    """Cover stale-generation early returns and exception paths in send/resync."""
    auth = MagicMock()
    validator = MagicMock()
    client = SmartAPIWebSocketClient(
        auth=auth,
        admission_validator=validator,
        quarantine_db_path=str(tmp_path / "ws_stale.duckdb"),
    )
    client._state = ConnectionState.CONNECTED

    # Line 351: _on_open with stale generation → early return
    stale_gen = client._generation_id - 1
    client._on_open(MagicMock(), generation=stale_gen)

    # Line 393: _on_data with non-bytes data → early return
    client._on_data(MagicMock(), "this_is_text_not_bytes", generation=client._generation_id)

    # Line 547: _on_error with stale generation → early return
    client._on_error(MagicMock(), Exception("test error"), generation=stale_gen)

    # Lines 652-653: _send_json with ws.send raising exception
    mock_ws_send_fail = MagicMock()
    mock_ws_send_fail.send.side_effect = Exception("WebSocket send failed")
    client._ws = mock_ws_send_fail
    client._send_json({"action": 1})  # Should log error, not raise

    # Lines 662-663: _trigger_stream_resync with ws.close raising exception
    mock_ws_close_fail = MagicMock()
    mock_ws_close_fail.close.side_effect = Exception("WebSocket close failed")
    client._ws = mock_ws_close_fail
    client._trigger_stream_resync("NSE", "2885")  # Should log warning, not raise

    client._state = ConnectionState.STOPPED


# ---------------------------------------------------------------------------
# Test 2: Pipeline certification edge cases
#   (lines 130, 145, 148-149, 221-222, 500-501, 616-617)
# ---------------------------------------------------------------------------

def test_pipeline_certification_and_dq_edges(tmp_path):
    """Cover empty hash, empty validator_version, JSON parse error, generic DQ exception,
    invalid order metadata JSON, and asset class lookup exception."""
    db = DuckDBManager(str(tmp_path / "pipe_cert_edge.duckdb"))
    pipe = StrategyPipeline(db=db, require_authoritative_certification=True)

    # --- Line 130: Dataset with empty transformation_hash AND empty raw_hash ---
    db.conn.execute("""
        INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name,
            raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment)
        VALUES ('ds_no_hash', 'SYM_NH', 'SYM_NH', '1d', 'NSE', 'TEST', '', '', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED')
    """)
    db.conn.execute("""
        INSERT INTO historical_candles (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id)
        VALUES ('SYM_NH', '1', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 100, 'SPLIT_ADJUSTED', 'TEST', 'ds_no_hash')
    """)
    with pytest.raises(DataQualityError, match="no immutable content hash"):
        pipe.load_candles("SYM_NH", "1d", adjustment=PriceAdjustment.SPLIT_ADJUSTED)

    # --- Lines 145, 148-149: Cert with empty validator_version → skip; cert with invalid checks_json → {} ---
    db.conn.execute("""
        INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name,
            raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment)
        VALUES ('ds_bad_cert', 'SYM_BC', 'SYM_BC', '1d', 'NSE', 'TEST', 'h_raw_bc', 'h_tf_bc', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED')
    """)
    # Cert 1: empty validator_version → line 145 continue
    db.conn.execute("""
        INSERT INTO data_quality_certifications (certification_id, dataset_id, validator_version, check_count, issue_count, checks_json, status, started_at, completed_at)
        VALUES ('cert_empty_ver', 'ds_bad_cert', '', 6, 0, '{}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    # Cert 2: invalid JSON in checks_json → lines 148-149 except
    db.conn.execute("""
        INSERT INTO data_quality_certifications (certification_id, dataset_id, validator_version, check_count, issue_count, checks_json, status, started_at, completed_at)
        VALUES ('cert_bad_json', 'ds_bad_cert', 'validator-v1', 6, 0, '{invalid', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    db.conn.execute("""
        INSERT INTO historical_candles (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id)
        VALUES ('SYM_BC', '2', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 100, 'SPLIT_ADJUSTED', 'TEST', 'ds_bad_cert')
    """)
    with pytest.raises(DataQualityError, match="lacks active CERTIFIED batch"):
        pipe.load_candles("SYM_BC", "1d", adjustment=PriceAdjustment.SPLIT_ADJUSTED)

    # --- Lines 221-222: Generic (non-DataQualityError) exception inside DQ gate → wrapped as DataQualityError ---
    pipe2 = StrategyPipeline(db=db, require_authoritative_certification=True)
    db.conn.execute("""
        INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name,
            raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment)
        VALUES ('ds_exc', 'SYM_EXC', 'SYM_EXC', '1d', 'NSE', 'TEST', 'h_raw_exc', 'h_tf_exc', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED')
    """)
    db.conn.execute("""
        INSERT INTO historical_candles (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id)
        VALUES ('SYM_EXC', '3', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 100, 'SPLIT_ADJUSTED', 'TEST', 'ds_exc')
    """)
    # Poison data_quality_certifications query to raise a RuntimeError
    real_conn = db.conn
    mock_conn = MagicMock()
    def poisoned_execute(query, *args, **kwargs):
        if "data_quality_certifications" in str(query) and len(args) > 0 and "ds_exc" in str(args):
            raise RuntimeError("DB connection lost")
        return real_conn.execute(query, *args, **kwargs)
    mock_conn.execute.side_effect = poisoned_execute
    with patch.object(pipe2.db, "conn", mock_conn):
        with pytest.raises(DataQualityError, match="certification failed.*DB connection lost"):
            pipe2.load_candles("SYM_EXC", "1d", adjustment=PriceAdjustment.SPLIT_ADJUSTED)

    # --- Lines 500-501: order metadata with invalid JSON in _persist_single_asset_attribution ---
    result_mock = MagicMock()
    result_mock.run_id = "run_inv_ord"
    result_mock.symbol = "TEST"
    result_mock.fills = pd.DataFrame([
        {"fill_id": "f1", "order_id": "o1", "side": "BUY", "quantity": 10.0, "price": 100.0,
         "timestamp": "2026-01-05 09:15:00", "fees": 2.0, "metadata_json": "{}"},
    ])
    result_mock.orders = pd.DataFrame([
        {"order_id": "o1", "metadata_json": "{INVALID_JSON}"},  # Invalid JSON → lines 500-501
    ])
    exec_model = MagicMock(slippage_bps=5.0, spread_bps=2.0)
    attr_df, rt_df, cost_df = pipe._persist_single_asset_attribution(result_mock, exec_model, persist=False)
    assert len(attr_df) == 1  # Fill processed despite invalid order metadata

    # --- Lines 616-617: _lookup_asset_class exception path ---
    mock_conn2 = MagicMock()
    mock_conn2.execute.side_effect = Exception("lookup failure")
    with patch.object(db, "conn", mock_conn2):
        ac = pipe._lookup_asset_class(symbol="UNKNOWN", exchange="NSE")
    assert ac is not None  # Falls back to infer_asset_class


# ---------------------------------------------------------------------------
# Test 3: Pipeline paper session edges (lines 321, 349-351, 396)
# ---------------------------------------------------------------------------

def test_pipeline_paper_session_edge_branches(tmp_path):
    """Cover cross-sectional missing universe, strict calendar OOS, empty paper risk orders."""
    db = DuckDBManager(str(tmp_path / "pipe_paper_edge.duckdb"))
    pipe = StrategyPipeline(db=db, require_authoritative_certification=False)

    # --- Line 396: _apply_paper_risk with empty orders → early return ---
    empty_result = MagicMock()
    empty_result.orders = pd.DataFrame()
    pipe._apply_paper_risk(empty_result, 100000.0)  # Should return immediately

    # --- Line 321: cross-sectional paper session with empty universe ---
    cross_meta = MagicMock()
    cross_meta.scope = StrategyScope.CROSS_SECTIONAL

    mock_promo_instance = MagicMock(unsafe=True)
    with patch("trading_stack.pipeline.PromotionEngine", return_value=mock_promo_instance), \
         patch("trading_stack.pipeline.StrategyRegistry") as mock_reg:
        mock_reg.metadata.return_value = cross_meta
        with pytest.raises(ValueError, match="Cross-sectional paper sessions require"):
            pipe.run_paper_session(
                strategy_name="cross_strat", approved_run_id="run_cross",
                symbol="RELIANCE", timeframe="1d", universe=[],
            )

    # --- Lines 349-351: strict calendar with out-of-session bars ---
    pipe_strict = StrategyPipeline(db=db, require_authoritative_certification=False, strict_calendar=True)

    single_meta = MagicMock()
    single_meta.scope = StrategyScope.SINGLE_ASSET

    mock_validation = MagicMock()
    mock_validation.out_of_session_count = 3  # Non-zero → triggers line 350-351

    # Insert a candle to load
    db.conn.execute("INSERT INTO instrument_master (symbol, exch_seg, token) VALUES ('OOS_SYM', 'NSE', '9999');")
    for i in range(1, 50):
        m = (i // 28) + 1
        d = (i % 28) + 1
        dt_str = f"2026-0{m:01d}-{d:02d} 09:15:00+05:30"
        db.conn.execute(f"""
            INSERT INTO historical_candles VALUES ('OOS_SYM', '9999', 'NSE', '1d', '{dt_str}',
            100.0+{i}, 110.0+{i}, 90.0+{i}, 105.0+{i}, 1000, 'SPLIT_ADJUSTED', 'TEST', 'ds_oos', CURRENT_TIMESTAMP)
        """)

    mock_promo_instance2 = MagicMock(unsafe=True)
    with patch("trading_stack.pipeline.PromotionEngine", return_value=mock_promo_instance2), \
         patch("trading_stack.pipeline.StrategyRegistry") as mock_reg:
        mock_reg.metadata.return_value = single_meta
        # Patch the calendar's validate_bars to return out-of-session
        cal_key = pipe_strict._lookup_asset_class(symbol="OOS_SYM", exchange="NSE")
        with patch.object(pipe_strict.calendars[cal_key], "validate_bars", return_value=mock_validation):
            with pytest.raises(ValueError, match="outside the verified market calendar"):
                pipe_strict.run_paper_session(
                    strategy_name="trend_following", approved_run_id="run_oos",
                    symbol="OOS_SYM", timeframe="1d",
                )


# ---------------------------------------------------------------------------
# Test 4: Paper engine token resolution fallbacks
#   (lines 291-299, 340-341)
# ---------------------------------------------------------------------------

def test_paper_engine_candle_token_resolution_and_identity_mismatch(tmp_path):
    """Cover historical_candles token fallback and identity mismatch rejection."""
    db = DuckDBManager(str(tmp_path / "paper_token.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())

    # Insert candle with token for fallback resolution (no instrument_master row, no universe_snapshot_members)
    db.conn.execute("""
        INSERT INTO historical_candles VALUES ('TOKFB', '12345', 'NSE', '1d',
        '2026-01-05 09:15:00+05:30', 1500.0, 1510.0, 1490.0, 1505.0, 10000,
        'SPLIT_ADJUSTED', 'TEST', 'ds_tokfb', CURRENT_TIMESTAMP)
    """)

    engine = ForwardPaperSessionEngine(db=db, calendar=cal, risk_engine=risk_eng)

    # --- Lines 291-299: Token resolved via historical_candles fallback ---
    # Opening tick with CORRECT symbol, token, exchange, quality
    correct_obs = OpeningTickObservation(
        symbol="TOKFB", token="12345", exchange="NSE", price=1505.0,
        received_at_utc=datetime(2026, 1, 6, 3, 45, 1, tzinfo=timezone.utc),
        exchange_timestamp=datetime(2026, 1, 6, 3, 45, 0, tzinfo=timezone.utc),
        quality_state="TRUSTED", sequence_number=1,
    )
    bar_dict = {
        "timestamp": "2026-01-06 09:15:00+05:30", "open": 1500.0, "close": 1510.0,
        "volume": 10000, "exchange": "NSE",
        "open_tick_observation": correct_obs,
    }
    pending = {"target_position": 0.10, "reason": "signal", "signal_timestamp": "2026-01-05 15:30:00+05:30"}
    _, _, _, _, _, _, _, order_ok, _, _, _, _ = engine._execute_pending(
        "sess_tokfb", "TOKFB", bar_dict, pending, 100000.0, 0.0, 0.0,
        100000.0, 100000.0, 100000.0, None, "ENTRY", 0.0, 0.0,
        execution_mode="TRUE_NEXT_OPEN",
    )
    assert order_ok["status"] == "FILLED"

    # --- Lines 340-341: Identity MISMATCH (wrong exchange) → rejection ---
    wrong_exchange_obs = OpeningTickObservation(
        symbol="TOKFB", token="12345", exchange="BSE", price=1505.0,  # Wrong exchange
        received_at_utc=datetime(2026, 1, 6, 3, 45, 1, tzinfo=timezone.utc),
        exchange_timestamp=datetime(2026, 1, 6, 3, 45, 0, tzinfo=timezone.utc),
        quality_state="TRUSTED", sequence_number=2,
    )
    bar_dict2 = {
        "timestamp": "2026-01-06 09:15:00+05:30", "open": 1500.0, "close": 1510.0,
        "volume": 10000, "exchange": "NSE",
        "open_tick_observation": wrong_exchange_obs,
    }
    _, _, _, _, _, _, _, order_rej, _, _, _, _ = engine._execute_pending(
        "sess_tokfb2", "TOKFB", bar_dict2, pending, 100000.0, 0.0, 0.0,
        100000.0, 100000.0, 100000.0, None, "ENTRY", 0.0, 0.0,
        execution_mode="TRUE_NEXT_OPEN",
    )
    assert order_rej["status"] == "REJECTED"
    assert "MISSED_LIVE_OPEN_PRICE" in order_rej["metadata_json"]


# ---------------------------------------------------------------------------
# Test 5: Portfolio paper engine missing target_weight column and no-new-session
#   (lines 362, 274-281)
# ---------------------------------------------------------------------------

def test_portfolio_paper_missing_weight_and_no_session(tmp_path):
    """Cover _risk_adjust_targets with missing target_weight and no-new-session early return."""
    db = DuckDBManager(str(tmp_path / "pp_edge.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())

    engine = ForwardPortfolioPaperSessionEngine(
        db=db, calendar=cal, risk_engine=risk_eng,
        require_authoritative_certification=False,
    )

    # --- Line 362: _risk_adjust_targets with targets missing target_weight column ---
    date = pd.Timestamp("2026-01-06", tz="UTC")
    day_df = pd.DataFrame([
        {"symbol": "INFY", "open": 1500.0, "close": 1510.0, "volume": 10000,
         "exchange": "NSE", "lagged_adv20": 100000.0, "lagged_traded_value": 500000000.0},
    ]).set_index("symbol", drop=False)

    # Targets WITHOUT target_weight column → line 362
    targets_no_wt = pd.DataFrame([
        {"timestamp": date, "symbol": "INFY", "reason": "rank_1", "rank": 1},
    ])
    adj, decisions = engine._risk_adjust_targets(
        targets_no_wt, day_df, quantities={}, cash=100000.0,
        prices={"INFY": 1510.0}, capital=100000.0,
        daily_start_equity=100000.0, peak_equity=100000.0,
    )
    assert "target_weight" in adj.columns
    assert float(adj.iloc[0]["target_weight"]) == 0.0


# ---------------------------------------------------------------------------
# Test 6: WebSocket quarantine worker close exception (lines 531-532)
#   and stop with quarantine items in queue (line 240)
# ---------------------------------------------------------------------------

def test_websocket_quarantine_worker_close_and_stop_drain(tmp_path):
    """Cover quarantine worker conn.close() exception and stop() queue drain."""
    auth = MagicMock()
    validator = MagicMock()
    client = SmartAPIWebSocketClient(
        auth=auth,
        admission_validator=validator,
        quarantine_db_path=str(tmp_path / "ws_qw.duckdb"),
    )

    # Lines 531-532: quarantine worker conn.close() raises exception
    mock_conn = MagicMock()
    mock_conn.close.side_effect = Exception("Close error in quarantine worker")
    client._quarantine_db_path = str(tmp_path / "ws_qw.duckdb")
    client._state = ConnectionState.STOPPED
    # Patch duckdb.connect in the module where it's imported (local import)
    with patch("duckdb.connect", return_value=mock_conn):
        client._quarantine_worker()

    # Line 240: stop() with items in quarantine queue (drain loop)
    client2 = SmartAPIWebSocketClient(
        auth=auth,
        admission_validator=validator,
        quarantine_db_path=str(tmp_path / "ws_qw2.duckdb"),
    )
    client2._state = ConnectionState.CONNECTED
    client2._quarantine_queue.put_nowait((MagicMock(), {}))  # Item in queue
    client2._ws = None
    client2.stop()
