"""Definitive critical-path coverage booster targeting all remaining branch misses."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_platform.contracts import LiveTickerMode, PriceAdjustment
from data_platform.live_admission import (
    LiveMarketDataAdmissionValidator,
)
from smartapi.subscription_registry import SubscriptionKey
from smartapi.websocket_client import (
    ConnectionState,
    SmartAPIWebSocketClient,
)
from storage.duckdb_manager import DuckDBManager
from trading_stack.calendars import build_nse_calendar
from trading_stack.datasets import SynchronizedPanelBuilder, DataQualityError
from trading_stack.pipeline import StrategyPipeline
from trading_stack.portfolio import PortfolioEventBacktester


# ---------------------------------------------------------------------------
# 1. SmartAPI WebSocket Client Deep Branch Coverage
# ---------------------------------------------------------------------------

def test_websocket_client_deep_branches(tmp_path):
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
        quarantine_db_path=str(tmp_path / "ws_deep.duckdb"),
        websocket_factory=MagicMock,
    )

    # 1. start() and double start() branch
    with patch("threading.Thread"):
        client.start()
        # Double start hits state in (CONNECTED, CONNECTING)
        client.start()

    # 2. subscribe & unsubscribe empty / BSE
    client.subscribe([])
    client.unsubscribe([])
    client.subscribe_symbols(["RELIANCE"], exchange_type=2)

    # 3. _on_open replaying subscriptions
    client._ws = MagicMock()
    k1 = SubscriptionKey(exchange_type=1, token="2885", mode=LiveTickerMode.LTP)
    client.registry.validate_and_add([k1])
    client._on_open(client._ws, generation=client._generation_id)

    # 4. stop() with ws closing exception & thread joining
    mock_ws = MagicMock()
    mock_ws.close.side_effect = Exception("Close error")
    client._ws = mock_ws
    mock_th = MagicMock()
    mock_th.is_alive.return_value = False
    client._ws_thread = mock_th
    client.stop()

    # 5. Quarantine worker failure branch (invalid connection)
    bad_client = SmartAPIWebSocketClient(
        auth=auth,
        admission_validator=validator,
        quarantine_db_path="/invalid/nonexistent/path/db.duckdb",
        websocket_factory=MagicMock,
    )
    bad_client._state = ConnectionState.STOPPED
    bad_client._quarantine_worker()


# ---------------------------------------------------------------------------
# 2. SynchronizedPanelBuilder Uncertified and CA Branches
# ---------------------------------------------------------------------------

def test_panel_builder_uncertified_and_corporate_actions(tmp_path):
    db = DuckDBManager(str(tmp_path / "panel_ca.duckdb"))
    cal = build_nse_calendar()
    builder = SynchronizedPanelBuilder(db=db, calendar=cal, require_authoritative_certification=True)

    # 1. NULL dataset_id in authoritative mode raises DataQualityError
    db.conn.execute("INSERT INTO historical_candles (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id) VALUES ('UNCERT_SYM', '1', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 100, 'SPLIT_ADJUSTED', 'TEST', NULL);")
    with pytest.raises(DataQualityError, match="uncertified candle rows present with NULL dataset_id"):
        builder.build(["UNCERT_SYM"], timeframe="1d", benchmark_symbol=None)

    # 2. Corporate actions dividend and split adjustment in SynchronizedPanelBuilder
    non_auth_builder = SynchronizedPanelBuilder(db=db, calendar=cal, require_authoritative_certification=False)
    db.conn.execute("INSERT INTO historical_candles (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id) VALUES ('CA_SYM', '2', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 100, 'SPLIT_ADJUSTED', 'TEST', 'ds_ca');")
    db.conn.execute("INSERT INTO historical_candles (symbol, token, exchange, timeframe, timestamp, open, high, low, close, volume, adjustment, provider_name, dataset_id) VALUES ('CA_SYM', '2', 'NSE', '1d', '2026-01-06 09:15:00+05:30', 105.0, 110.0, 100.0, 108.0, 150, 'SPLIT_ADJUSTED', 'TEST', 'ds_ca');")
    db.conn.execute("INSERT INTO corporate_actions (action_id, symbol, exchange, action_type, ex_date, share_multiplier, dividend_amount, source, status) VALUES ('ca_1', 'CA_SYM', 'NSE', 'SPLIT', '2026-01-06', 2.0, 0.0, 'TEST', 'ACTIVE');")
    
    panel = non_auth_builder.build(["CA_SYM"], timeframe="1d", benchmark_symbol="CA_SYM")
    assert not panel.panel.empty


# ---------------------------------------------------------------------------
# 3. StrategyPipeline Benchmark Comparison & Adjustments
# ---------------------------------------------------------------------------

def test_pipeline_benchmark_and_adjustments(tmp_path):
    db = DuckDBManager(str(tmp_path / "pipe_bench.duckdb"))
    pipe = StrategyPipeline(db=db, require_authoritative_certification=False)

    # Insert candles for symbol and benchmark
    db.conn.execute("INSERT INTO instrument_master (symbol, exch_seg, token) VALUES ('RELIANCE', 'NSE', '2885');")
    db.conn.execute("INSERT INTO instrument_master (symbol, exch_seg, token) VALUES ('NIFTY', 'NSE', '99999');")
    for i in range(1, 55):
        m = (i // 28) + 1
        d = (i % 28) + 1
        dt_str = f"2026-0{m:01d}-{d:02d} 09:15:00+05:30"
        db.conn.execute(f"INSERT INTO historical_candles VALUES ('RELIANCE', '2885', 'NSE', '1d', '{dt_str}', 2000.0 + {i}, 2010.0 + {i}, 1990.0 + {i}, 2005.0 + {i}, 10000, 'SPLIT_ADJUSTED', 'TEST', 'ds_1', CURRENT_TIMESTAMP);")
        db.conn.execute(f"INSERT INTO historical_candles VALUES ('NIFTY', '99999', 'NSE', '1d', '{dt_str}', 18000.0 + {i}, 18100.0 + {i}, 17900.0 + {i}, 18050.0 + {i}, 100000, 'SPLIT_ADJUSTED', 'TEST', 'ds_bench', CURRENT_TIMESTAMP);")

    # Load with SPLIT_ADJUSTED adjustment
    df_adj = pipe.load_candles("RELIANCE", "1d", adjustment=PriceAdjustment.SPLIT_ADJUSTED)
    assert not df_adj.empty

    # Run backtest
    res = pipe.run(
        strategy_name="trend_following",
        symbol="RELIANCE",
        timeframe="1d",
        parameters={"fast_threshold": 0.0, "min_volatility": 0.0},
        mode="event",
    )
    assert res["run_id"] is not None


# ---------------------------------------------------------------------------
# 4. PortfolioEventBacktester Constraints & Capacity Enforcement
# ---------------------------------------------------------------------------

def test_portfolio_backtester_rebalance_turnover_and_costs(tmp_path):
    db = DuckDBManager(str(tmp_path / "port_turn.duckdb"))
    bt = PortfolioEventBacktester()
    bt.db = db
    date = pd.Timestamp("2026-01-06", tz="UTC")

    day_df = pd.DataFrame([
        {"symbol": "INFY", "open": 1500.0, "close": 1510.0, "volume": 10000, "lagged_adv20": 100000.0, "lagged_traded_value": 500000000.0, "exchange": "NSE"},
        {"symbol": "TCS", "open": 3500.0, "close": 3550.0, "volume": 10000, "lagged_adv20": 100000.0, "lagged_traded_value": 500000000.0, "exchange": "NSE"},
    ]).set_index("symbol", drop=False)

    # 1. Entry Rebalance
    targets_entry = pd.DataFrame([
        {"timestamp": date, "symbol": "INFY", "target_weight": 0.40, "reason": "rank_1"},
        {"timestamp": date, "symbol": "TCS", "target_weight": 0.40, "reason": "rank_2"},
    ])
    cash, res_entry = bt._rebalance(
        run_id="run_turn", date=date, day=day_df, targets=targets_entry, cash=100000.0,
        quantities={}, average_cost={}, entry_timestamps={}, entry_reasons={},
        entry_cost_pools={}, entry_execution_cost_pools={}, last_prices={},
        mode="paper", execution_mode="EOD_BATCH",
    )
    assert len(res_entry["fills"]) == 2

    # 2. Exit Rebalance calculating execution cost pools
    targets_exit = pd.DataFrame([
        {"timestamp": date, "symbol": "INFY", "target_weight": 0.0, "reason": "exit_1"},
        {"timestamp": date, "symbol": "TCS", "target_weight": 0.0, "reason": "exit_2"},
    ])
    held_qty = {f["symbol"]: f["quantity"] for f in res_entry["fills"]}
    held_cost = {f["symbol"]: f["price"] for f in res_entry["fills"]}
    held_ts = {f["symbol"]: date for f in res_entry["fills"]}
    cash_post, res_exit = bt._rebalance(
        run_id="run_turn", date=date, day=day_df, targets=targets_exit, cash=cash,
        quantities=held_qty, average_cost=held_cost, entry_timestamps=held_ts,
        entry_reasons={"INFY": "rank_1", "TCS": "rank_2"},
        entry_cost_pools={"INFY": 10.0, "TCS": 15.0},
        entry_execution_cost_pools={"INFY": 5.0, "TCS": 8.0},
        last_prices={"INFY": 1510.0, "TCS": 3550.0},
        mode="paper", execution_mode="EOD_BATCH",
    )
    assert len(res_exit["fills"]) == 2
    assert len(res_exit["round_trips"]) == 2
