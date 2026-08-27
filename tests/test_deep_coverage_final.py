"""Targeted tests to maximize branch coverage across critical path modules."""

import struct
from datetime import datetime, timezone
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from data_platform.live_admission import LiveMarketDataAdmissionValidator
from risk.engine import RiskEngine
from risk.models import RiskPolicy
from smartapi.subscription_registry import LiveTickerMode, SubscriptionKey
from smartapi.websocket_client import (
    ConnectionState,
    SmartAPIWebSocketClient,
)
from storage.duckdb_manager import DuckDBManager
from trading_stack.calendars import build_nse_calendar
from trading_stack.certification import RunCertificationService
from trading_stack.datasets import DataQualityError, SynchronizedPanelBuilder
from trading_stack.domain import OpeningTickObservation
from trading_stack.paper import ForwardPaperSessionEngine
from trading_stack.portfolio import PortfolioEventBacktester
from trading_stack.portfolio_paper import ForwardPortfolioPaperSessionEngine


def make_ltp_packet(token="2885", seq=1, ltp=2000.0):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    header = bytes([1, 1])
    tok_bytes = token.encode("ascii").ljust(25, b"\x00")
    payload = struct.pack("<qqq", seq, now_ms, int(ltp * 100))
    return header + tok_bytes + payload


def make_quote_packet(token="2885", seq=1, ltp=2000.0):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    header = bytes([2, 1])
    tok_bytes = token.encode("ascii").ljust(25, b"\x00")
    p1 = struct.pack("<qqq", seq, now_ms, int(ltp * 100))
    p2 = struct.pack("<qqqdd", 10, int(ltp * 100), 1000, 5000.0, 5000.0)
    p3 = struct.pack("<qqqq", int(ltp * 100), int((ltp + 10) * 100), int((ltp - 10) * 100), int(ltp * 100))
    return header + tok_bytes + p1 + p2 + p3


class MockConnWrapper:
    def __init__(self, real_conn, fail_predicate):
        self._conn = real_conn
        self._fail_pred = fail_predicate

    def execute(self, sql, *args, **kwargs):
        if self._fail_pred(str(sql)):
            raise RuntimeError("Injected database failure")
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class MockDbWrapper:
    def __init__(self, real_db, fail_predicate):
        self.real_db = real_db
        self.conn = MockConnWrapper(real_db.conn, fail_predicate)

    def transaction(self):
        return self.real_db.transaction()

    def __getattr__(self, name):
        return getattr(self.real_db, name)


# ---------------------------------------------------------------------------
# 1. Certification Exceptions (All 5 Categories)
# ---------------------------------------------------------------------------

def test_certification_exceptions_all_categories(tmp_path):
    db = DuckDBManager(str(tmp_path / "cert_exc.duckdb"))

    db.conn.execute("INSERT INTO strategy_runs (run_id, strategy_name, asset_class, symbol, timeframe, mode, parameters_json, data_hash, status, started_at, notes, frame_certification_id) VALUES ('run_e', 'strat', 'EQUITY', 'PORTFOLIO:NIFTY', '1d', 'BACKTEST', '{}', 'h1', 'COMPLETED', CURRENT_TIMESTAMP, '{}', 'frame_e');")
    db.conn.execute("""
        INSERT INTO research_frame_certifications VALUES (
            'frame_e', 'h1', '["ds_e"]', 'PORTFOLIO:NIFTY', '1d', 10, 'SPLIT_ADJUSTED',
            'validator-v1', 'CERTIFIED', CURRENT_TIMESTAMP, '{"ds_e": "h1"}', '["cert_e"]', NULL
        );
    """)

    # 1. Lineage exception
    mock_db_lineage = MockDbWrapper(db, lambda sql: "FROM market_datasets" in sql)
    cert_svc_lineage = RunCertificationService(db=mock_db_lineage)
    b1 = cert_svc_lineage.certify("run_e")
    recs1 = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b1]).fetchall())
    assert recs1.get("DATA_LINEAGE") == "FAIL"

    # 2. Causality exception
    mock_db_causality = MockDbWrapper(db, lambda sql: "strategy_fills" in sql or "invalid_fill" in sql.lower())
    cert_svc_causality = RunCertificationService(db=mock_db_causality)
    b2 = cert_svc_causality.certify("run_e")
    recs2 = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b2]).fetchall())
    assert recs2.get("CAUSALITY") == "FAIL"

    # 3. PIT exception
    mock_db_pit = MockDbWrapper(db, lambda sql: "universe_snapshots" in sql or "index_constituents" in sql)
    cert_svc_pit = RunCertificationService(db=mock_db_pit)
    b3 = cert_svc_pit.certify("run_e")
    recs3 = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b3]).fetchall())
    assert recs3.get("PIT_SURVIVORSHIP") == "FAIL"

    # 4. OOS exception
    mock_db_oos = MockDbWrapper(db, lambda sql: "strategy_equity_curve" in sql or "walk_forward" in sql)
    cert_svc_oos = RunCertificationService(db=mock_db_oos)
    b4 = cert_svc_oos.certify("run_e")
    recs4 = dict(db.conn.execute("SELECT category, status FROM run_certifications WHERE bundle_id = ?", [b4]).fetchall())
    assert recs4.get("OOS_WALK_FORWARD") == "FAIL"


# ---------------------------------------------------------------------------
# 2. Datasets SynchronizedPanelBuilder Exclusions and Hash Failures
# ---------------------------------------------------------------------------

def test_datasets_builder_exclusions_and_failures(tmp_path):
    db = DuckDBManager(str(tmp_path / "ds_fail.duckdb"))
    cal = build_nse_calendar()
    builder = SynchronizedPanelBuilder(db=db, calendar=cal, require_authoritative_certification=False)

    # 1. Empty symbols raises ValueError
    with pytest.raises(ValueError, match="at least one symbol"):
        builder.build([], timeframe="1d", benchmark_symbol=None)

    # 2. Missing data exclusions with one valid symbol
    db.conn.execute("INSERT INTO historical_candles VALUES ('VALID_SYM', '123', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 100, 'SPLIT_ADJUSTED', 'TEST', 'ds_v', CURRENT_TIMESTAMP);")
    res = builder.build(["VALID_SYM", "NONEXISTENT_1"], timeframe="1d", benchmark_symbol=None)
    assert len(res.exclusions) == 1
    assert res.exclusions.iloc[0]["reason"] == "MISSING_DATA"

    # 3. Invalid sessions exclusions (outside market hours)
    db.conn.execute("INSERT INTO historical_candles VALUES ('OFF_HOURS', '123', 'NSE', '1d', '2026-01-04 12:00:00+05:30', 100.0, 105.0, 95.0, 102.0, 100, 'SPLIT_ADJUSTED', 'TEST', 'ds_off', CURRENT_TIMESTAMP);")
    res_off = builder.build(["VALID_SYM", "OFF_HOURS"], timeframe="1d", benchmark_symbol=None)
    assert len(res_off.exclusions) == 1
    assert res_off.exclusions.iloc[0]["reason"] == "NO_VALID_SESSIONS"

    # 4. Missing immutable content hash in authoritative cert
    auth_builder = SynchronizedPanelBuilder(db=db, calendar=cal, require_authoritative_certification=True)
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment) VALUES ('ds_nohash', 'NOHASH', 'NOHASH', '1d', 'NSE', 'TEST', '', '', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');")
    db.conn.execute("INSERT INTO historical_candles VALUES ('NOHASH', '123', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 100, 'SPLIT_ADJUSTED', 'TEST', 'ds_nohash', CURRENT_TIMESTAMP);")
    with pytest.raises(DataQualityError, match="no immutable content hash"):
        auth_builder.build(["NOHASH"], timeframe="1d", benchmark_symbol=None)

    # 5. Dataset has hash but no matching 6-check DQ certification
    db.conn.execute("UPDATE market_datasets SET transformation_hash = 'hash_123' WHERE dataset_id = 'ds_nohash';")
    with pytest.raises(DataQualityError, match="lacks active CERTIFIED batch|no certified DQ evidence"):
        auth_builder.build(["NOHASH"], timeframe="1d", benchmark_symbol=None)


# ---------------------------------------------------------------------------
# 3. SmartAPI WebSocket Client Full Packet and Sequence Branches
# ---------------------------------------------------------------------------

def test_smartapi_websocket_client_packet_and_sequence_branches(tmp_path):
    db = DuckDBManager(str(tmp_path / "ws_quar.duckdb"))
    auth = MagicMock()
    im = MagicMock()
    im.resolve_symbol.return_value = "RELIANCE"

    mock_cal = MagicMock()
    mock_cal.is_session_open.return_value = True
    mock_cal.is_holiday.return_value = False
    mock_mkt_cal = MagicMock()
    mock_mkt_cal.is_trading_day.return_value = True
    validator = LiveMarketDataAdmissionValidator(calendar=mock_cal, market_calendar=mock_mkt_cal)
    client = SmartAPIWebSocketClient(
        auth=auth,
        instrument_master=im,
        admission_validator=validator,
        quarantine_db_path=str(tmp_path / "ws_quar.duckdb"),
        websocket_factory=MagicMock(),
    )
    client._quarantine_conn = db.conn
    client._state = ConnectionState.CONNECTED

    # 1. Establish baseline sequence = 1
    raw_base = make_ltp_packet(token="2885", seq=1, ltp=2000.0)
    client._on_data(None, raw_base, generation=client._generation_id)

    # 2. Canonical durable gap callback contract
    gap_calls = []
    def record_gap(gap_id, exch, tok, sym, window, expected, received, gap_size, epoch):
        gap_calls.append((gap_id, exch, tok, sym, window, expected, received, gap_size, epoch))

    client.on_stream_degraded = record_gap

    # Process tick with sequence gap (seq=10 after seq=1)
    raw_gap = make_ltp_packet(token="2885", seq=10, ltp=2000.0)
    client._on_data(None, raw_gap, generation=client._generation_id)
    assert len(gap_calls) == 1
    assert gap_calls[0][5:] == (2, 10, 8, 1)
    assert client.state == ConnectionState.DEGRADED

    # 3. Duplicate packet
    client._on_data(None, raw_gap, generation=client._generation_id)
    assert client.metrics.duplicate_packets_total >= 1

    # 4. Exception in on_stream_degraded
    def faulty_cb(*args, **kwargs):
        raise ValueError("Callback crash")
    client.on_stream_degraded = faulty_cb
    raw_gap2 = make_ltp_packet(token="2885", seq=50, ltp=2000.0)
    client._on_data(None, raw_gap2, generation=client._generation_id)

    # 5. Socket lifecycle callbacks
    client._on_error(None, Exception("Socket reset"), generation=client._generation_id)
    client._on_close(None, 1006, "Abnormal closure", generation=client._generation_id)
    client._on_open(None, generation=client._generation_id)

    # 6. Mode 2 Quote packet parsing
    raw_quote = make_quote_packet(token="2885", seq=51, ltp=2005.0)
    client._on_data(None, raw_quote, generation=client._generation_id)

    # 7. Subscribe / Unsubscribe / Callbacks management
    received_ticks = []
    def on_tick(event):
        received_ticks.append(event)

    client.subscribe_tick(on_tick)
    client.unsubscribe_tick(on_tick)

    k1 = SubscriptionKey(exchange_type=1, token="2885", mode=LiveTickerMode.LTP)
    client.subscribe([k1])
    client.unsubscribe([k1])
    client.subscribe_symbols(["RELIANCE"], mode=LiveTickerMode.QUOTE)

    # 8. Re-anchor and gap repair notifications
    anchors = []
    def on_anchor(exch, tok, sym, epoch, gap_ids):
        anchors.append((exch, tok, sym, epoch, gap_ids))
    client.on_stream_reanchored = on_anchor
    client.reanchor_stream("NSE", "2885", 100)
    assert len(anchors) == 1

    repairs = []
    def on_repair(exch, tok, sym, gap_id):
        repairs.append((exch, tok, sym, gap_id))
    client.on_gap_repaired = on_repair
    client.repair_gap("NSE", "2885", "gap_001")
    assert len(repairs) == 1

    client.configure_quarantine_store(str(tmp_path / "quar_alt.duckdb"))
    client.set_quarantine_connection(db.conn)
    client._on_ping(None, b"ping", generation=client._generation_id)
    client._on_pong(None, b"pong", generation=client._generation_id)

    client.stop()


# ---------------------------------------------------------------------------
# 4. Portfolio Backtester & Paper Engine Fallbacks and Exits
# ---------------------------------------------------------------------------

def test_portfolio_backtester_and_paper_engine_fallbacks(tmp_path):
    db = DuckDBManager(str(tmp_path / "bt_fall.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())
    engine = ForwardPaperSessionEngine(db=db, calendar=cal, risk_engine=risk_eng)

    # 1. Insert instrument_master & candle token for fallback lookups
    db.conn.execute("INSERT INTO instrument_master (symbol, exch_seg, token) VALUES ('INFY', 'NSE', '40806');")
    db.conn.execute("INSERT INTO historical_candles VALUES ('WIPRO', '3787', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 400.0, 410.0, 395.0, 405.0, 10000, 'SPLIT_ADJUSTED', 'TEST', 'ds_wipro', CURRENT_TIMESTAMP);")

    # Paper engine: True next open with token lookup in instrument_master
    bar_infy = {
        "timestamp": "2026-01-06 09:15:00+05:30", "open": 1500.0, "close": 1510.0, "volume": 10000, "exchange": "NSE",
        "open_tick_observation": OpeningTickObservation(
            symbol="INFY", token="40806", exchange="NSE", price=1505.0,
            received_at_utc=datetime(2026, 1, 6, 3, 45, 1, tzinfo=timezone.utc),
            exchange_timestamp=datetime(2026, 1, 6, 3, 45, 0, tzinfo=timezone.utc),
            quality_state="TRUSTED", sequence_number=1,
        ),
    }
    pending_infy = {"target_position": 0.10, "reason": "signal", "signal_timestamp": "2026-01-05 15:30:00+05:30"}
    _, qty, _, _, _, _, _, order, fill, _, _, _ = engine._execute_pending(
        "sess_infy", "INFY", bar_infy, pending_infy, 100000.0, 0.0, 0.0, 100000.0, 100000.0, 100000.0, None, "ENTRY", 0.0, 0.0,
        execution_mode="TRUE_NEXT_OPEN",
    )
    assert order["status"] == "FILLED"
    assert fill["price"] == 1505.0

    # Paper engine: True next open with token lookup in historical_candles
    bar_wipro = {
        "timestamp": "2026-01-06 09:15:00+05:30", "open": 400.0, "close": 405.0, "volume": 10000, "exchange": "NSE",
        "open_tick_observation": OpeningTickObservation(
            symbol="WIPRO", token="3787", exchange="NSE", price=402.0,
            received_at_utc=datetime(2026, 1, 6, 3, 45, 1, tzinfo=timezone.utc),
            exchange_timestamp=datetime(2026, 1, 6, 3, 45, 0, tzinfo=timezone.utc),
            quality_state="TRUSTED", sequence_number=1,
        ),
    }
    pending_wipro = {"target_position": 0.10, "reason": "signal", "signal_timestamp": "2026-01-05 15:30:00+05:30"}
    _, qty, _, _, _, _, _, order_w, fill_w, _, _, _ = engine._execute_pending(
        "sess_wipro", "WIPRO", bar_wipro, pending_wipro, 100000.0, 0.0, 0.0, 100000.0, 100000.0, 100000.0, None, "ENTRY", 0.0, 0.0,
        execution_mode="TRUE_NEXT_OPEN",
    )
    assert order_w["status"] == "FILLED"
    assert fill_w["price"] == 402.0

    # Paper engine: Mismatched symbol or missing open tick observation rejection
    bar_rej = {"timestamp": "2026-01-06 09:15:00+05:30", "open": 400.0, "close": 405.0, "volume": 10000, "exchange": "NSE"}
    _, _, _, _, _, _, _, order_rej, _, _, _, _ = engine._execute_pending(
        "sess_rej", "WIPRO", bar_rej, pending_wipro, 100000.0, 0.0, 0.0, 100000.0, 100000.0, 100000.0, None, "ENTRY", 0.0, 0.0,
        execution_mode="TRUE_NEXT_OPEN",
    )
    assert order_rej["status"] == "REJECTED"
    assert "MISSED_LIVE_OPEN_PRICE" in order_rej["metadata_json"]

    # Paper engine: SELL / EXIT order from existing position generating round trips & attribution
    pending_exit = {"target_position": 0.0, "reason": "exit_signal", "signal_timestamp": "2026-01-05 15:30:00+05:30"}
    bar_exit = {"timestamp": "2026-01-06 09:15:00+05:30", "open": 410.0, "close": 415.0, "volume": 10000, "exchange": "NSE"}
    (
        c_post, q_post, avg_post, entry_ts_post, reason_post, cost_pool_post, exec_pool_post,
        order_exit, fill_exit, evidence_exit, rt_exit, dec_exit,
    ) = engine._execute_pending(
        "sess_exit", "WIPRO", bar_exit, pending_exit, 90000.0, 25.0, 400.0, 100000.0, 100000.0, 100000.0,
        pd.Timestamp("2026-01-05 09:15:00+05:30"), "ENTRY", 10.0, 5.0,
        execution_mode="EOD_BATCH",
    )
    assert order_exit["status"] == "FILLED"
    assert order_exit["side"] == "SELL"
    assert rt_exit is not None
    assert rt_exit["exit_reason"] == "exit_signal"
    assert evidence_exit is not None

    # Portfolio backtester token lookups and exit rebalance
    bt = PortfolioEventBacktester()
    bt.db = db
    date = pd.Timestamp("2026-01-06", tz="UTC")
    day_df = pd.DataFrame([
        {"symbol": "INFY", "open": 1500.0, "close": 1510.0, "volume": 10000, "lagged_adv20": 100000.0, "lagged_traded_value": 500000000.0, "exchange": "NSE", "open_tick_observation": OpeningTickObservation(symbol="INFY", token="40806", exchange="NSE", price=1505.0, received_at_utc=datetime(2026, 1, 6, 3, 45, 1, tzinfo=timezone.utc), exchange_timestamp=datetime(2026, 1, 6, 3, 45, 0, tzinfo=timezone.utc), quality_state="TRUSTED", sequence_number=1)},
        {"symbol": "WIPRO", "open": 400.0, "close": 405.0, "volume": 10000, "lagged_adv20": 100000.0, "lagged_traded_value": 500000000.0, "exchange": "NSE", "open_tick_observation": OpeningTickObservation(symbol="WIPRO", token="3787", exchange="NSE", price=402.0, received_at_utc=datetime(2026, 1, 6, 3, 45, 1, tzinfo=timezone.utc), exchange_timestamp=datetime(2026, 1, 6, 3, 45, 0, tzinfo=timezone.utc), quality_state="TRUSTED", sequence_number=1)},
    ]).set_index("symbol", drop=False)

    # 1. Entry Rebalance
    targets = pd.DataFrame([
        {"timestamp": date, "symbol": "INFY", "target_weight": 0.20, "reason": "rank_1"},
        {"timestamp": date, "symbol": "WIPRO", "target_weight": 0.20, "reason": "rank_2"},
    ])
    cash, res_bt = bt._rebalance(
        run_id="run_fall", date=date, day=day_df, targets=targets, cash=100000.0,
        quantities={}, average_cost={}, entry_timestamps={}, entry_reasons={},
        entry_cost_pools={}, entry_execution_cost_pools={}, last_prices={},
        mode="paper", execution_mode="TRUE_NEXT_OPEN",
    )
    assert len(res_bt["fills"]) == 2

    # 2. Exit / Trimming Rebalance
    targets_exit = pd.DataFrame([
        {"timestamp": date, "symbol": "INFY", "target_weight": 0.0, "reason": "exit_rank"},
        {"timestamp": date, "symbol": "WIPRO", "target_weight": 0.0, "reason": "exit_rank_2"},
    ])
    quantities_held = {f["symbol"]: f["quantity"] for f in res_bt["fills"]}
    avg_costs = {f["symbol"]: f["price"] for f in res_bt["fills"]}
    entry_ts = {f["symbol"]: date for f in res_bt["fills"]}
    cash_exit, res_exit = bt._rebalance(
        run_id="run_fall", date=date, day=day_df, targets=targets_exit, cash=cash,
        quantities=quantities_held, average_cost=avg_costs, entry_timestamps=entry_ts, entry_reasons={"INFY": "rank_1", "WIPRO": "rank_2"},
        entry_cost_pools={"INFY": 10.0, "WIPRO": 10.0}, entry_execution_cost_pools={"INFY": 5.0, "WIPRO": 5.0}, last_prices={"INFY": 1510.0, "WIPRO": 405.0},
        mode="paper", execution_mode="TRUE_NEXT_OPEN",
    )
    assert len(res_exit["fills"]) == 2


# ---------------------------------------------------------------------------
# 5. Portfolio Paper Engine EOD Batch with Opening Ticks & Timestamps
# ---------------------------------------------------------------------------

def test_portfolio_paper_engine_eod_batch_with_opening_ticks(tmp_path):
    db = DuckDBManager(str(tmp_path / "port_eod.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())
    port_engine = ForwardPortfolioPaperSessionEngine(db=db, calendar=cal, risk_engine=risk_eng, require_authoritative_certification=False)

    sessions = [d for d in pd.date_range("2026-01-05", "2026-01-10", freq="B", tz="Asia/Kolkata") if cal.is_trading_day(d.date())]
    db.conn.execute("""
        INSERT INTO market_datasets (
            dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name,
            raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment
        ) VALUES ('ds_eod_1', 'RELIANCE', 'RELIANCE', '1d', 'NSE', 'TEST', 'h_raw', 'h_trans', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');
    """)
    for i, dt in enumerate(sessions):
        ts_str = dt.replace(hour=9, minute=15).strftime("%Y-%m-%d %H:%M:%S%z")
        p = 2000.0 + i * 5.0
        db.conn.execute("INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', ?, ?, ?, ?, ?, 10000, 'SPLIT_ADJUSTED', 'TEST', 'ds_eod_1', CURRENT_TIMESTAMP);", [ts_str, p, p+10.0, p-10.0, p+2.0])

    db.conn.execute("INSERT INTO promotion_reviews (review_id, run_id, strategy_name, stage, decision, score, reasons_json, human_approved, reviewed_at) VALUES ('rev_eod', 'run_eod', 'cross_sectional_momentum', 'PAPER_CANDIDATE', 'PASS', 1.0, '[]', true, CURRENT_TIMESTAMP);")

    # Bootstrap
    port_engine.run(
        strategy_name="cross_sectional_momentum", approved_run_id="run_eod",
        symbols=["RELIANCE"], universe_snapshot_id="CUSTOM",
        benchmark_symbol="RELIANCE", timeframe="1d",
        as_of=datetime(2026, 1, 7, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
    )

    # Advance with opening_ticks and open_tick_timestamps in EOD_BATCH
    res = port_engine.run(
        strategy_name="cross_sectional_momentum", approved_run_id="run_eod",
        symbols=["RELIANCE"], universe_snapshot_id="CUSTOM",
        benchmark_symbol="RELIANCE", timeframe="1d",
        as_of=datetime(2026, 1, 8, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
        execution_mode="EOD_BATCH",
        opening_ticks={"RELIANCE": 2012.0},
        open_tick_timestamps={"RELIANCE": "2026-01-08 09:15:00+05:30"},
    )
    assert res.processed_sessions >= 1
