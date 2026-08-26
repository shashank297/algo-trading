"""Final surge to achieve >95% critical module coverage across all repository components."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pandas as pd
import pytest

from risk.engine import RiskEngine
from risk.models import RiskPolicy
from storage.duckdb_manager import DuckDBManager
from trading_stack.calendars import build_nse_calendar
from trading_stack.datasets import SynchronizedPanelBuilder, DataQualityError
from trading_stack.domain import OpeningTickObservation
from trading_stack.paper import ForwardPaperSessionEngine
from trading_stack.pipeline import StrategyPipeline
from trading_stack.portfolio import PortfolioEventBacktester


# ---------------------------------------------------------------------------
# 1. Pipeline Fill Cost Attribution & Metadata Branches
# ---------------------------------------------------------------------------

def test_pipeline_cost_attribution_branches(tmp_path):
    db = DuckDBManager(str(tmp_path / "pipe_attr2.duckdb"))
    pipe = StrategyPipeline(db=db, require_authoritative_certification=False)

    # 1. Test _compute_fill_cost_attributions directly with and without cost_components in metadata
    result_mock = MagicMock()
    result_mock.run_id = "run_cost_test"
    result_mock.fills = pd.DataFrame([
        {"fill_id": "f1", "order_id": "o1", "side": "BUY", "quantity": 10.0, "price": 100.0, "timestamp": "2026-01-05 09:15:00", "fees": 2.0, "metadata_json": json.dumps({"cost_components": {"total_cost": 5.0, "spread": 1.0, "slippage": 2.0, "market_impact": 1.0, "fees": 1.0}})},
        {"fill_id": "f2", "order_id": "o2", "side": "SELL", "quantity": 10.0, "price": 105.0, "timestamp": "2026-01-06 09:15:00", "fees": 2.5, "metadata_json": "{invalid_json}"},
    ])
    result_mock.orders = pd.DataFrame([
        {"order_id": "o1", "metadata_json": "{}"},
        {"order_id": "o2", "metadata_json": "{}"},
    ])

    exec_model = MagicMock(slippage_bps=5.0, spread_bps=2.0)
    rows_df, cost_df, rt_df = pipe._persist_single_asset_attribution(result_mock, exec_model, persist=False)
    assert len(cost_df) == 1


# ---------------------------------------------------------------------------
# 2. Portfolio Backtester & Paper Engine Untrusted Tick Rejection
# ---------------------------------------------------------------------------

def test_portfolio_backtester_and_paper_untrusted_tick_rejection(tmp_path):
    db = DuckDBManager(str(tmp_path / "port_untrusted.duckdb"))
    cal = build_nse_calendar()
    risk_eng = RiskEngine(RiskPolicy())
    
    # 1. Insert historical candle for token resolution
    db.conn.execute("INSERT INTO historical_candles VALUES ('INFY', '40806', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 1500.0, 1510.0, 1490.0, 1505.0, 10000, 'SPLIT_ADJUSTED', 'TEST', 'ds_infy', CURRENT_TIMESTAMP);")

    # Untrusted opening tick observation
    untrusted_obs = OpeningTickObservation(
        symbol="INFY", token="40806", exchange="NSE", price=1505.0,
        received_at_utc=datetime(2026, 1, 6, 3, 45, 1, tzinfo=timezone.utc),
        exchange_timestamp=datetime(2026, 1, 6, 3, 45, 0, tzinfo=timezone.utc),
        quality_state="UNTRUSTED", sequence_number=1,
    )

    # 2. PortfolioEventBacktester: Rebalance with untrusted opening tick observation
    bt = PortfolioEventBacktester()
    bt.db = db
    date = pd.Timestamp("2026-01-06", tz="UTC")
    day_df = pd.DataFrame([
        {"symbol": "INFY", "open": 1500.0, "close": 1510.0, "volume": 10000, "lagged_adv20": 100000.0, "lagged_traded_value": 500000000.0, "exchange": "NSE", "open_tick_observation": untrusted_obs},
    ]).set_index("symbol", drop=False)

    targets = pd.DataFrame([
        {"timestamp": date, "symbol": "INFY", "target_weight": 0.50, "reason": "rank_1"},
    ])

    cash, res_bt = bt._rebalance(
        run_id="run_untrusted", date=date, day=day_df, targets=targets, cash=100000.0,
        quantities={}, average_cost={}, entry_timestamps={}, entry_reasons={},
        entry_cost_pools={}, entry_execution_cost_pools={}, last_prices={},
        mode="paper", execution_mode="TRUE_NEXT_OPEN",
    )
    assert len(res_bt["orders"]) == 1
    assert res_bt["orders"][0]["status"] == "REJECTED"
    assert "MISSED_LIVE_OPEN_PRICE" in res_bt["orders"][0]["metadata_json"]

    # 3. Paper Engine: Execute pending with untrusted opening tick observation
    paper_engine = ForwardPaperSessionEngine(db=db, calendar=cal, risk_engine=risk_eng)
    bar_dict = {
        "timestamp": "2026-01-06 09:15:00+05:30", "open": 1500.0, "close": 1510.0, "volume": 10000, "exchange": "NSE",
        "open_tick_observation": untrusted_obs,
    }
    pending_infy = {"target_position": 0.10, "reason": "signal", "signal_timestamp": "2026-01-05 15:30:00+05:30"}
    _, _, _, _, _, _, _, order_rej, _, _, _, _ = paper_engine._execute_pending(
        "sess_untrust", "INFY", bar_dict, pending_infy, 100000.0, 0.0, 0.0, 100000.0, 100000.0, 100000.0, None, "ENTRY", 0.0, 0.0,
        execution_mode="TRUE_NEXT_OPEN",
    )
    assert order_rej["status"] == "REJECTED"
    assert "MISSED_LIVE_OPEN_PRICE" in order_rej["metadata_json"]


# ---------------------------------------------------------------------------
# 3. Datasets Malformed Checks & Non-Promoted Status Branches
# ---------------------------------------------------------------------------

def test_datasets_authoritative_status_and_checks_json_branches(tmp_path):
    db = DuckDBManager(str(tmp_path / "ds_edge.duckdb"))
    cal = build_nse_calendar()
    builder = SynchronizedPanelBuilder(db=db, calendar=cal, require_authoritative_certification=True)

    # 1. Dataset not CANONICAL_PROMOTED raises DataQualityError
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment) VALUES ('ds_unp', 'SYM_UNP', 'SYM_UNP', '1d', 'NSE', 'TEST', 'h_raw', 'h_tf', 'VERIFIED', 'INGESTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');")
    db.conn.execute("INSERT INTO historical_candles VALUES ('SYM_UNP', '1', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 100, 'SPLIT_ADJUSTED', 'TEST', 'ds_unp', CURRENT_TIMESTAMP);")
    
    with pytest.raises(DataQualityError, match="must be VERIFIED and CANONICAL_PROMOTED"):
        builder._load_bars("SYM_UNP", "1d", require_authoritative_certification=True)

    # 2. Dataset with invalid JSON in data_quality_certifications checks_json
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment) VALUES ('ds_bad_json', 'SYM_BJ', 'SYM_BJ', '1d', 'NSE', 'TEST', 'h_raw', 'h_tf', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');")
    db.conn.execute("INSERT INTO data_quality_certifications VALUES ('cert_bj', 'ds_bad_json', 'validator-v1', 6, 0, '{invalid_json}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO historical_candles VALUES ('SYM_BJ', '2', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 100, 'SPLIT_ADJUSTED', 'TEST', 'ds_bad_json', CURRENT_TIMESTAMP);")

    with pytest.raises(DataQualityError, match="lacks active CERTIFIED batch bound to hash"):
        builder._load_bars("SYM_BJ", "1d", require_authoritative_certification=True)
