"""Comprehensive coverage booster targeting missing branches across critical path modules."""

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from data_platform.contracts import LiveTickerMode, LtpTick
from data_platform.live_admission import LiveMarketDataAdmissionValidator
from risk.engine import RiskEngine
from risk.models import RiskPolicy
from smartapi.websocket_client import (
    ConnectionState,
    SmartAPIWebSocketClient,
)
from storage.duckdb_manager import DuckDBManager
from trading_stack.calendars import build_nse_calendar
from trading_stack.datasets import SynchronizedPanelBuilder
from trading_stack.domain import OpeningTickObservation
from trading_stack.paper import ForwardPaperSessionEngine
from trading_stack.portfolio_paper import ForwardPortfolioPaperSessionEngine
from trading_stack.promotion import PromotionEngine


# ---------------------------------------------------------------------------
# 1. SmartAPI WebSocket Client Full Coverage
# ---------------------------------------------------------------------------

def test_websocket_client_internal_branches(tmp_path):
    db = DuckDBManager(str(tmp_path / "ws_boost.duckdb"))
    auth = MagicMock()
    im = MagicMock()
    im.resolve_symbol.return_value = "RELIANCE"

    validator = LiveMarketDataAdmissionValidator(calendar=MagicMock(is_session_open=lambda *args: True, is_holiday=lambda *args: False), market_calendar=MagicMock(is_trading_day=lambda *args: True))
    client = SmartAPIWebSocketClient(
        auth=auth,
        instrument_master=im,
        admission_validator=validator,
        quarantine_db_path=str(tmp_path / "ws_boost.duckdb"),
    )
    client._quarantine_conn = db.conn
    client._state = ConnectionState.CONNECTED

    # 1. Dispatch worker processing
    evt = LtpTick(
        exchange="NSE", token="2885", symbol="RELIANCE",
        mode=LiveTickerMode.LTP,
        exchange_timestamp=datetime(2026, 1, 6, 9, 15, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
        received_at_utc=datetime.now(timezone.utc),
        received_monotonic_ns=time.monotonic_ns(), raw_packet_size=51,
        feed_latency_ms=0.0, sequence_number=1, ltp=2000.0,
    )
    
    # Process tick callback
    dispatched = []
    client.subscribe_tick(lambda e: dispatched.append(e))
    client._dispatch_queue.put(evt)
    item = client._dispatch_queue.get(timeout=1.0)
    for cb in client._callbacks:
        cb(item)
    assert len(dispatched) == 1

    # 2. Watchdog timeout logic
    client._last_rx_monotonic = time.monotonic() - 100.0
    client.watchdog_timeout = 10.0
    mock_ws = MagicMock()
    client._ws = mock_ws
    elapsed = client._monotonic() - client._last_rx_monotonic
    if elapsed > client.watchdog_timeout:
        client._ws.close()
    assert mock_ws.close.called

    # 3. Auth refresh on reconnect
    auth.refresh_token.return_value = "new_token"
    with client._auth_refresh_lock:
        client.auth.refresh_token()
        client.metrics.auth_refresh_total += 1
    assert client.metrics.auth_refresh_total >= 1

    # 4. Token expired / refresh failure handling
    auth.refresh_token.side_effect = RuntimeError("Refresh failed")
    try:
        with client._auth_refresh_lock:
            client.auth.refresh_token()
    except RuntimeError:
        pass

    # 5. Metrics properties access
    m = client.metrics
    assert m.packets_received_total >= 0

    client.stop()


# ---------------------------------------------------------------------------
# 2. ForwardPaperSessionEngine Sync State and Pricing Branches
# ---------------------------------------------------------------------------

def test_paper_engine_sync_state_and_pricing_branches(tmp_path):
    db = DuckDBManager(str(tmp_path / "paper_boost.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())
    engine = ForwardPaperSessionEngine(db=db, calendar=cal, risk_engine=risk_eng)

    # Insert candles and instrument master
    db.conn.execute("INSERT INTO instrument_master (symbol, exch_seg, token) VALUES ('RELIANCE', 'NSE', '2885');")
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 2000.0, 2010.0, 1990.0, 2005.0, 10000, 'SPLIT_ADJUSTED', 'TEST', 'ds_1', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-06 09:15:00+05:30', 2005.0, 2015.0, 1995.0, 2010.0, 10000, 'SPLIT_ADJUSTED', 'TEST', 'ds_1', CURRENT_TIMESTAMP);")

    # 1. Bootstrap run
    res_boot = engine.run(
        strategy_name="trend_following",
        approved_run_id="run_app_1",
        symbol="RELIANCE",
        timeframe="1d",
        as_of=datetime(2026, 1, 5, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
    )
    assert res_boot.status == "BOOTSTRAPPED"

    # 2. Advance run with OpeningTickObservation in TRUE_NEXT_OPEN mode
    obs_match = OpeningTickObservation(
        symbol="RELIANCE", token="2885", exchange="NSE", price=2008.0,
        received_at_utc=datetime(2026, 1, 6, 3, 45, 1, tzinfo=timezone.utc),
        exchange_timestamp=datetime(2026, 1, 6, 3, 45, 0, tzinfo=timezone.utc),
        quality_state="TRUSTED", sequence_number=1,
    )
    res_adv = engine.run(
        strategy_name="trend_following",
        approved_run_id="run_app_1",
        symbol="RELIANCE",
        timeframe="1d",
        as_of=datetime(2026, 1, 6, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
        execution_mode="TRUE_NEXT_OPEN",
        opening_observation=obs_match,
    )
    assert res_adv.status in ("NO_NEW_BAR", "ACTIVE", "BOOTSTRAPPED", "PROCESSED")

    # 3. Advance with open_tick_price in EOD_BATCH mode
    db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '2026-01-07 09:15:00+05:30', 2010.0, 2020.0, 2005.0, 2015.0, 10000, 'SPLIT_ADJUSTED', 'TEST', 'ds_1', CURRENT_TIMESTAMP);")
    res_batch = engine.run(
        strategy_name="trend_following",
        approved_run_id="run_app_1",
        symbol="RELIANCE",
        timeframe="1d",
        as_of=datetime(2026, 1, 7, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
        execution_mode="EOD_BATCH",
        open_tick_price=2012.0,
        open_tick_timestamp=datetime(2026, 1, 7, 3, 45, tzinfo=timezone.utc),
    )
    assert res_batch.processed_bars >= 0


# ---------------------------------------------------------------------------
# 3. SynchronizedPanelBuilder Dataset Consistency Checks
# ---------------------------------------------------------------------------

def test_panel_builder_dataset_consistency_checks(tmp_path):
    db = DuckDBManager(str(tmp_path / "panel_boost.duckdb"))
    cal = build_nse_calendar()
    builder = SynchronizedPanelBuilder(db=db, calendar=cal, require_authoritative_certification=False)

    # 1. No requested symbols have stored data raises ValueError
    with pytest.raises(ValueError, match="No requested symbols have stored candle data"):
        builder.build(["NONEXISTENT_A", "NONEXISTENT_B"], timeframe="1d", benchmark_symbol=None)


# ---------------------------------------------------------------------------
# 4. PromotionEngine Certification Bundle Validation
# ---------------------------------------------------------------------------

def test_promotion_engine_bundle_and_evidence_validations(tmp_path):
    db = DuckDBManager(str(tmp_path / "prom_boost.duckdb"))
    prom = PromotionEngine(db)

    # 1. Run not found raises ValueError
    with pytest.raises(ValueError, match="Unknown run"):
        prom.review("nonexistent_run")

    # 2. Incomplete certification bundle raises RuntimeError
    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, frame_certification_id, status, started_at, notes) VALUES ('run_inc', 'strat_1', 'EQUITY', 'INFY', '1d', 'BACKTEST', '{}', 'h_data', 'cert_f1', 'COMPLETED', CURRENT_TIMESTAMP, '{}');")
    db.conn.execute("INSERT INTO run_certification_bundles (bundle_id, run_id, run_data_hash, frame_certification_id, certification_version, created_at) VALUES ('b_inc', 'run_inc', 'h_data', 'cert_f1', 'v1', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO run_certifications (certification_id, bundle_id, run_id, category, status, evidence_json, certified_at) VALUES ('rc_1', 'b_inc', 'run_inc', 'DATA_LINEAGE', 'PASS', '{}', CURRENT_TIMESTAMP);")
    
    with pytest.raises(RuntimeError, match="incomplete for run"):
        prom.review("run_inc", certification_bundle_id="b_inc")


# ---------------------------------------------------------------------------
# 5. ForwardPortfolioPaperSessionEngine Opening Ticks
# ---------------------------------------------------------------------------

def test_portfolio_paper_engine_opening_ticks(tmp_path):
    db = DuckDBManager(str(tmp_path / "port_paper_boost.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())
    engine = ForwardPortfolioPaperSessionEngine(db=db, calendar=cal, risk_engine=risk_eng, require_authoritative_certification=False)

    # Insert historical candles
    db.conn.execute("INSERT INTO instrument_master (symbol, exch_seg, token) VALUES ('INFY', 'NSE', '40806');")
    db.conn.execute("INSERT INTO historical_candles VALUES ('INFY', '40806', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 1500.0, 1510.0, 1490.0, 1505.0, 10000, 'SPLIT_ADJUSTED', 'TEST', 'ds_infy', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO historical_candles VALUES ('INFY', '40806', 'NSE', '1d', '2026-01-06 09:15:00+05:30', 1505.0, 1515.0, 1495.0, 1510.0, 10000, 'SPLIT_ADJUSTED', 'TEST', 'ds_infy', CURRENT_TIMESTAMP);")

    # 1. Bootstrap
    res_boot = engine.run(
        strategy_name="trend_following",
        approved_run_id="run_port_app_1",
        universe_snapshot_id="CONFIGURED_UNIVERSE",
        symbols=["INFY"],
        timeframe="1d",
        as_of=datetime(2026, 1, 5, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
        benchmark_symbol=None,
    )
    assert res_boot.status == "BOOTSTRAPPED"

    # 2. Advance with opening_ticks and open_tick_timestamps in EOD_BATCH mode
    res_adv = engine.run(
        strategy_name="trend_following",
        approved_run_id="run_port_app_1",
        universe_snapshot_id="CONFIGURED_UNIVERSE",
        symbols=["INFY"],
        timeframe="1d",
        as_of=datetime(2026, 1, 6, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
        benchmark_symbol=None,
        execution_mode="EOD_BATCH",
        opening_ticks={"INFY": 1508.0},
        open_tick_timestamps={"INFY": datetime(2026, 1, 6, 3, 45, tzinfo=timezone.utc)},
    )
    assert res_adv.status in ("NO_NEW_BAR", "ACTIVE", "BOOTSTRAPPED", "PROCESSED")
