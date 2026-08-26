"""Targeted coverage tests for StrategyPipeline and RealtimeBarAggregator."""

from datetime import datetime, timezone, timedelta
import pytest
import pandas as pd
from unittest.mock import patch
from zoneinfo import ZoneInfo

from storage.duckdb_manager import DuckDBManager
from trading_stack.pipeline import StrategyPipeline, DataQualityError as PipelineDQError
from trading_stack.live_aggregator import RealtimeBarAggregator
from data_platform.contracts import LtpTick, QuoteTick, LiveTickerMode
from trading_stack.calendars import build_nse_calendar


def test_pipeline_composed_frame_validations(tmp_path):
    db = DuckDBManager(str(tmp_path / "pipe_val.duckdb"))
    pipe = StrategyPipeline(db=db, require_authoritative_certification=False)

    # 1. Non-authoritative quality_report failure branch
    db.conn.execute("INSERT INTO historical_candles VALUES ('FAIL_SYM', '123', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 100, 'SPLIT_ADJUSTED', 'TEST', 'ds_fail', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO quality_report (symbol, timeframe, check_type, issue_count, checked_at, dataset_id, certification_id) VALUES ('FAIL_SYM', '1d', 'ZERO_VOLUME', 5, CURRENT_TIMESTAMP, 'ds_fail', 'cert_001');")
    with pytest.raises(PipelineDQError, match="failed ZERO_VOLUME check"):
        pipe.load_candles("FAIL_SYM", "1d", adjustment="SPLIT_ADJUSTED")

    # Authoritative mode setup
    auth_pipe = StrategyPipeline(db=db, require_authoritative_certification=True)

    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment) VALUES ('ds_dup', 'DUP_SYM', 'DUP_SYM', '1d', 'NSE', 'TEST', 'h_raw', 'h_dup', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');")
    db.conn.execute("INSERT INTO data_quality_certifications VALUES ('cert_dup', 'ds_dup', 'validator-v1', 6, 0, '{\"dataset_content_hash\": \"h_dup\"}', 'CERTIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);")
    for chk in ["schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity"]:
        db.conn.execute("INSERT INTO quality_report (symbol, timeframe, check_type, issue_count, checked_at, dataset_id, certification_id) VALUES ('DUP_SYM', '1d', ?, 0, CURRENT_TIMESTAMP, 'ds_dup', 'cert_dup');", [chk])

    db.conn.execute("INSERT INTO historical_candles VALUES ('DUP_SYM', '123', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 100, 'SPLIT_ADJUSTED', 'TEST', 'ds_dup', CURRENT_TIMESTAMP);")

    # 2. Duplicate timestamps in composed frame via adjustment output
    dup_df = pd.DataFrame([
        {"symbol": "DUP_SYM", "exchange": "NSE", "timeframe": "1d", "timestamp": "2026-01-05 09:15:00+05:30", "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": 100.0, "dataset_id": "ds_dup", "adjustment": "SPLIT_ADJUSTED", "provider_name": "TEST"},
        {"symbol": "DUP_SYM", "exchange": "NSE", "timeframe": "1d", "timestamp": "2026-01-05 09:15:00+05:30", "open": 101.0, "high": 106.0, "low": 96.0, "close": 103.0, "volume": 150.0, "dataset_id": "ds_dup", "adjustment": "SPLIT_ADJUSTED", "provider_name": "TEST"},
    ])
    with patch("trading_stack.pipeline.PriceAdjustmentEngine.adjust_ohlcv", return_value=dup_df):
        with pytest.raises(PipelineDQError, match="duplicate timestamps"):
            auth_pipe.load_candles("DUP_SYM", "1d", adjustment="SPLIT_ADJUSTED")

    # 3. Non-monotonic timestamps
    non_mono_df = pd.DataFrame([
        {"symbol": "DUP_SYM", "exchange": "NSE", "timeframe": "1d", "timestamp": "2026-01-06 09:15:00+05:30", "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": 100.0, "dataset_id": "ds_dup", "adjustment": "SPLIT_ADJUSTED", "provider_name": "TEST"},
        {"symbol": "DUP_SYM", "exchange": "NSE", "timeframe": "1d", "timestamp": "2026-01-05 09:15:00+05:30", "open": 101.0, "high": 106.0, "low": 96.0, "close": 103.0, "volume": 150.0, "dataset_id": "ds_dup", "adjustment": "SPLIT_ADJUSTED", "provider_name": "TEST"},
    ])
    with patch("trading_stack.pipeline.PriceAdjustmentEngine.adjust_ohlcv", return_value=non_mono_df):
        with pytest.raises(PipelineDQError, match="strictly monotonic"):
            auth_pipe.load_candles("DUP_SYM", "1d", adjustment="SPLIT_ADJUSTED")

    # 4. OHLC integrity violations
    bad_ohlc_df = pd.DataFrame([
        {"symbol": "DUP_SYM", "exchange": "NSE", "timeframe": "1d", "timestamp": "2026-01-05 09:15:00+05:30", "open": 100.0, "high": 90.0, "low": 110.0, "close": 102.0, "volume": 100.0, "dataset_id": "ds_dup", "adjustment": "SPLIT_ADJUSTED", "provider_name": "TEST"},
    ])
    with patch("trading_stack.pipeline.PriceAdjustmentEngine.adjust_ohlcv", return_value=bad_ohlc_df):
        with pytest.raises(PipelineDQError, match="OHLC integrity violations"):
            auth_pipe.load_candles("DUP_SYM", "1d", adjustment="SPLIT_ADJUSTED")


def test_live_realtime_aggregator_edge_branches(tmp_path):
    db = DuckDBManager(str(tmp_path / "agg_edge.duckdb"))
    cal = build_nse_calendar()

    # Pre-populate stream_gap_events and stream_gaps
    db.conn.execute("INSERT INTO stream_gap_events (gap_id, exchange, token, symbol, start_time, end_time, gap_size, epoch, status, recorded_at) VALUES ('gap_1', 'NSE', '2885', 'RELIANCE', '2026-01-05 09:15:00+05:30', '2026-01-05 09:20:00+05:30', 5, 1, 'UNREPAIRED', CURRENT_TIMESTAMP);")
    db.conn.execute("INSERT INTO stream_gaps (gap_id, token, symbol, exchange, expected_sequence, received_sequence, gap_size, stream_epoch, detected_at, gap_status) VALUES ('gap_2', '40806', 'INFY', 'NSE', 10, 15, 5, 1, CURRENT_TIMESTAMP, 'UNREPAIRED');")

    agg = RealtimeBarAggregator(timeframe="1m", market_calendar=cal)
    agg.allowed_lateness = timedelta(seconds=0)
    agg.load_unresolved_gaps(db)
    assert "RELIANCE" in agg._untrusted_windows
    assert "INFY" in agg._untrusted_windows

    # 1. Bar subscriber callback
    emitted_bars = []
    def on_bar(bar):
        emitted_bars.append(bar)
    agg.subscribe_bar(on_bar)

    # 2. Non-positive price drop
    tick_zero = LtpTick(
        exchange="NSE", token="2885", symbol="RELIANCE", mode=LiveTickerMode.LTP,
        exchange_timestamp=datetime(2026, 1, 5, 9, 15, 1, tzinfo=ZoneInfo("Asia/Kolkata")),
        received_at_utc=datetime(2026, 1, 5, 3, 45, 1, tzinfo=timezone.utc),
        received_monotonic_ns=1000, raw_packet_size=51, feed_latency_ms=0.0,
        sequence_number=1, ltp=0.0,
    )
    assert agg.process_tick(tick_zero) == []

    # 3. Process valid quote tick
    tick_valid = QuoteTick(
        exchange="NSE", token="2885", symbol="RELIANCE", mode=LiveTickerMode.QUOTE,
        exchange_timestamp=datetime(2026, 1, 5, 9, 15, 1, tzinfo=ZoneInfo("Asia/Kolkata")),
        received_at_utc=datetime(2026, 1, 5, 3, 45, 1, tzinfo=timezone.utc),
        received_monotonic_ns=1000, raw_packet_size=123, feed_latency_ms=0.0,
        sequence_number=1, ltp=2000.0, last_traded_qty=10, average_traded_price=2000.0,
        cumulative_volume=100, total_buy_qty=1000.0, total_sell_qty=1000.0,
        day_open=1995.0, day_high=2005.0, day_low=1990.0, day_close=2000.0,
    )
    agg.process_tick(tick_valid)
    assert "RELIANCE" in agg._open_bars

    snap = agg.get_current_bar_snapshot("RELIANCE")
    assert snap is not None
    assert snap.close == 2000.0

    # 4. Process tick in next minute window (triggers bar emission)
    tick_next = QuoteTick(
        exchange="NSE", token="2885", symbol="RELIANCE", mode=LiveTickerMode.QUOTE,
        exchange_timestamp=datetime(2026, 1, 5, 9, 16, 1, tzinfo=ZoneInfo("Asia/Kolkata")),
        received_at_utc=datetime(2026, 1, 5, 3, 46, 1, tzinfo=timezone.utc),
        received_monotonic_ns=2000, raw_packet_size=123, feed_latency_ms=0.0,
        sequence_number=2, ltp=2005.0, last_traded_qty=20, average_traded_price=2002.0,
        cumulative_volume=150, total_buy_qty=1000.0, total_sell_qty=1000.0,
        day_open=1995.0, day_high=2005.0, day_low=1990.0, day_close=2000.0,
    )
    bars = agg.process_tick(tick_next)
    assert len(bars) == 1
    assert len(emitted_bars) == 1
    assert emitted_bars[0].volume == 10.0

    # 5. Flush elapsed windows
    closed_elapsed = agg.close_elapsed_windows(datetime(2026, 1, 5, 9, 20, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
    assert len(closed_elapsed) == 1
