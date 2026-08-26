"""Final targeted coverage booster pushing critical module coverage safely beyond 95%."""

import queue
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd

from data_platform.contracts import LiveTickerMode, LtpTick
from data_platform.live_admission import LiveMarketDataAdmissionValidator, TickAdmissionResult, TickAdmissionAction, AdmissionReasonCode
from smartapi.subscription_registry import SubscriptionKey
from smartapi.websocket_client import (
    ConnectionState,
    SmartAPIWebSocketClient,
)
from storage.duckdb_manager import DuckDBManager
from trading_stack.pipeline import StrategyPipeline
from trading_stack.portfolio import PortfolioEventBacktester


# ---------------------------------------------------------------------------
# 1. SmartAPI WebSocket Client Queue & Exception Isolation Branches
# ---------------------------------------------------------------------------

def test_websocket_client_queues_and_edge_branches(tmp_path):
    db = DuckDBManager(str(tmp_path / "ws_edge.duckdb"))
    auth = MagicMock()
    im = MagicMock()
    im.resolve_symbol.return_value = "RELIANCE"
    im.resolve_token.return_value = "2885"

    validator = LiveMarketDataAdmissionValidator(
        calendar=MagicMock(is_session_open=lambda *args: True, is_holiday=lambda *args: False),
        market_calendar=MagicMock(is_trading_day=lambda *args: True)
    )
    client = SmartAPIWebSocketClient(
        auth=auth,
        instrument_master=im,
        admission_validator=validator,
        quarantine_db_path=str(tmp_path / "ws_edge.duckdb"),
    )
    client._quarantine_conn = db.conn
    client._state = ConnectionState.CONNECTED

    # 1. on_stream_reanchored callback exception handling
    def bad_anchor_cb(*args):
        raise RuntimeError("Anchor callback error")
    client.on_stream_reanchored = bad_anchor_cb
    client.reanchor_stream("NSE", "2885", 100)

    # 2. subscribe & unsubscribe with active websocket mock
    mock_ws = MagicMock()
    client._ws = mock_ws
    k1 = SubscriptionKey(exchange_type=1, token="2885", mode=LiveTickerMode.LTP)
    client.subscribe([k1])
    assert mock_ws.send.called

    client.unsubscribe([k1])
    assert mock_ws.send.call_count >= 2

    # 3. subscribe_symbols with symbol resolution
    keys = client.subscribe_symbols(["RELIANCE"], mode=LiveTickerMode.QUOTE, exchange_type=1)
    assert len(keys) == 1
    assert keys[0].token == "2885"

    # 4. _on_data with generation mismatch
    raw_dummy = b"\x01" * 50
    client._on_data(None, raw_dummy, generation=client._generation_id - 1)

    # 5. Full quarantine queue handling
    client._quarantine_queue = queue.Queue(maxsize=1)
    client._quarantine_queue.put_nowait((MagicMock(), {}))
    adm_rej = TickAdmissionResult(
        token="2885", symbol="RELIANCE", exchange="NSE",
        action=TickAdmissionAction.QUARANTINE,
        reasons=(AdmissionReasonCode.OUT_OF_SESSION_HOURS,),
        tick_timestamp=datetime.now(timezone.utc),
        received_timestamp=datetime.now(timezone.utc),
        price=2000.0, volume=100.0,
    )
    with patch.object(validator, "validate", return_value=adm_rej):
        client._on_data(None, raw_dummy, generation=client._generation_id)

    # 6. Full dispatch queue handling
    client._dispatch_queue = queue.Queue(maxsize=1)
    client._dispatch_queue.put_nowait(MagicMock())
    adm_pass = TickAdmissionResult(
        token="2885", symbol="RELIANCE", exchange="NSE",
        action=TickAdmissionAction.ACCEPT,
        reasons=(AdmissionReasonCode.VALID_TICK,),
        tick_timestamp=datetime.now(timezone.utc),
        received_timestamp=datetime.now(timezone.utc),
        price=2000.0, volume=100.0,
    )
    with patch.object(validator, "validate", return_value=adm_pass):
        with patch("smartapi.websocket_client.SmartStreamDecoder.decode", return_value=LtpTick(
            exchange="NSE", token="2885", symbol="RELIANCE", mode=LiveTickerMode.LTP,
            exchange_timestamp=datetime(2026, 1, 6, 9, 15, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
            received_at_utc=datetime.now(timezone.utc),
            received_monotonic_ns=time.monotonic_ns(), raw_packet_size=51,
            feed_latency_ms=0.0, sequence_number=1, ltp=2000.0,
        )):
            client._on_data(None, raw_dummy, generation=client._generation_id)
            assert client.metrics.dispatch_queue_drops >= 1

    client.stop()


# ---------------------------------------------------------------------------
# 2. StrategyPipeline Walk Forward & Cost Attribution Coverage
# ---------------------------------------------------------------------------

def test_pipeline_cost_attribution_and_metadata(tmp_path):
    db = DuckDBManager(str(tmp_path / "pipe_attr.duckdb"))
    pipe = StrategyPipeline(db=db, require_authoritative_certification=False)

    # Insert historical candles (at least 50 for lookback)
    db.conn.execute("INSERT INTO instrument_master (symbol, exch_seg, token) VALUES ('RELIANCE', 'NSE', '2885');")
    for i in range(1, 55):
        m = (i // 28) + 1
        d = (i % 28) + 1
        dt_str = f"2026-0{m:01d}-{d:02d} 09:15:00+05:30"
        db.conn.execute(f"INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '{dt_str}', 2000.0 + {i}, 2010.0 + {i}, 1990.0 + {i}, 2005.0 + {i}, 10000, 'SPLIT_ADJUSTED', 'TEST', 'ds_1', CURRENT_TIMESTAMP);")

    # Run backtest with execution model cost attribution
    res = pipe.run(
        strategy_name="trend_following",
        symbol="RELIANCE",
        timeframe="1d",
        parameters={"fast_threshold": 0.0, "min_volatility": 0.0},
        mode="event",
    )
    assert res is not None
    assert res["run_id"] is not None


# ---------------------------------------------------------------------------
# 3. PortfolioEventBacktester Capacity and Constraints
# ---------------------------------------------------------------------------

def test_portfolio_backtester_capacity_and_sector_constraints(tmp_path):
    db = DuckDBManager(str(tmp_path / "port_edge.duckdb"))
    bt = PortfolioEventBacktester()
    bt.db = db
    date = pd.Timestamp("2026-01-06", tz="UTC")

    day_df = pd.DataFrame([
        {"symbol": "INFY", "open": 1500.0, "close": 1510.0, "volume": 10000, "lagged_adv20": 100000.0, "lagged_traded_value": 500000000.0, "exchange": "NSE"},
        {"symbol": "TCS", "open": 3500.0, "close": 3550.0, "volume": 10000, "lagged_adv20": 100000.0, "lagged_traded_value": 500000000.0, "exchange": "NSE"},
    ]).set_index("symbol", drop=False)

    targets = pd.DataFrame([
        {"timestamp": date, "symbol": "INFY", "target_weight": 0.50, "reason": "rank_1"},
        {"timestamp": date, "symbol": "TCS", "target_weight": 0.50, "reason": "rank_2"},
    ])

    # Rebalance with capacity constraints
    cash, res = bt._rebalance(
        run_id="run_cap", date=date, day=day_df, targets=targets, cash=100000.0,
        quantities={}, average_cost={}, entry_timestamps={}, entry_reasons={},
        entry_cost_pools={}, entry_execution_cost_pools={}, last_prices={},
        mode="paper", execution_mode="EOD_BATCH",
    )
    assert len(res["orders"]) == 2
    assert len(res["fills"]) == 2
