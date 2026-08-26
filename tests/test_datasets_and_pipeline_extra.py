"""Additional targeted branch tests for datasets, sector mapping, and market data decoding."""

import pytest
import pandas as pd

from storage.duckdb_manager import DuckDBManager
from trading_stack.datasets import SynchronizedPanelBuilder
from trading_stack.calendars import build_nse_calendar


def test_sector_mapping_and_validation(tmp_path):
    db = DuckDBManager(str(tmp_path / "ds_extra.duckdb"))
    cal = build_nse_calendar()
    builder = SynchronizedPanelBuilder(db=db, calendar=cal, require_authoritative_certification=False)

    # 1. Registered snapshot with missing sectors raises ValueError
    db.conn.execute("INSERT INTO universe_snapshots (snapshot_id, name, source_url, effective_date, content_hash) VALUES ('NIFTY50_REG', 'NIFTY50', 'http://test', '2026-01-01', 'h_snap');")
    with pytest.raises(ValueError, match="Missing authoritative sector mapping"):
        builder._sector_map(["RELIANCE"], snapshot_id="NIFTY50_REG")

    # 2. Registered snapshot with valid sector mapping returns mapping dict
    db.conn.execute("INSERT INTO universe_snapshot_members (snapshot_id, symbol, provider_symbol, sector, exchange) VALUES ('NIFTY50_REG', 'RELIANCE', 'RELIANCE-EQ', 'ENERGY', 'NSE');")
    mapping = builder._sector_map(["RELIANCE"], snapshot_id="NIFTY50_REG")
    assert mapping.get("RELIANCE") == "ENERGY"

    # 3. Non-authoritative _latest_dataset_id
    db.conn.execute("INSERT INTO market_datasets (dataset_id, symbol, canonical_symbol, timeframe, exchange, provider_name, raw_hash, transformation_hash, status, lifecycle_status, declared_adjustment, adjustment) VALUES ('ds_lat', 'RELIANCE', 'RELIANCE', '1d', 'NSE', 'TEST', 'h1', 'h2', 'VERIFIED', 'CANONICAL_PROMOTED', 'SPLIT_ADJUSTED', 'SPLIT_ADJUSTED');")
    assert builder._latest_dataset_id("RELIANCE", "1d") == "ds_lat"
    assert builder._latest_dataset_id("NONEXISTENT", "1d") is None

    # 4. Filter sessions with intraday timeframe
    dt_valid = pd.Timestamp("2026-01-05 09:30:00+05:30")
    dt_invalid = pd.Timestamp("2026-01-05 08:30:00+05:30")
    bars_df = pd.DataFrame([
        {"timestamp": dt_valid, "open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0, "volume": 100.0},
        {"timestamp": dt_invalid, "open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0, "volume": 100.0},
    ])
    filtered = builder._valid_sessions(bars_df, timeframe="5m")
    assert len(filtered) == 1
    assert filtered.iloc[0]["timestamp"] == dt_valid

    # 5. _resolve_benchmark branches
    assert builder._resolve_benchmark(None, "1d") == (None, None)
    
    # Exact match from bars
    db.conn.execute("INSERT INTO historical_candles VALUES ('BENCH_EXACT', '123', 'NSE', '1d', '2026-01-05 09:15:00+05:30', 100.0, 105.0, 95.0, 102.0, 100, 'SPLIT_ADJUSTED', 'TEST', 'ds_b', CURRENT_TIMESTAMP);")
    assert builder._resolve_benchmark("BENCH_EXACT", "1d") == ("BENCH_EXACT", "EXACT")

    # Alias match from benchmark_aliases
    db.conn.execute("INSERT INTO benchmark_aliases (canonical_symbol, provider_symbol, relationship, approved_for_research, source) VALUES ('BENCH_ALIAS', 'PROXY_SYM', 'PROXY', true, 'TEST');")
    assert builder._resolve_benchmark("BENCH_ALIAS", "1d") == ("PROXY_SYM", "PROXY")

    # Unmapped benchmark returns (symbol, None)
    assert builder._resolve_benchmark("UNMAPPED", "1d") == ("UNMAPPED", None)

    # 6. PIT evidence hash
    db.conn.execute("INSERT INTO index_constituents_pit (universe_name, instrument_id, symbol, token, exchange, effective_from, effective_until, known_from, weight, inclusion_reason, exclusion_reason) VALUES ('NIFTY50', 'inst_1', 'RELIANCE', '2885', 'NSE', '2026-01-01', NULL, '2026-01-01', 0.10, 'initial', NULL);")
    h_pit = builder._pit_evidence_hash("NIFTY50")
    assert isinstance(h_pit, str) and len(h_pit) == 64
