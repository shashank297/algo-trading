"""Regression test for PIT candle joins across symbol rename boundaries using durable identity."""

import pandas as pd
from storage import DuckDBManager
from trading_stack.datasets import filter_frame_by_pit


def test_pit_candles_join_across_rename_boundary(tmp_path):
    """Candles for ADANIGAS (pre-2021) and ATGL (post-2021) must both match the same PIT constituent."""
    db_path = str(tmp_path / "pit_test.duckdb")
    db = DuckDBManager(db_path)

    # Insert PIT interval for ADANIGAS / ATGL spanning 2020 to 2022
    db.conn.execute("""
        INSERT INTO index_constituents_pit (
            universe_name, instrument_id, symbol, token, exchange,
            effective_from, effective_until, known_from, weight,
            inclusion_reason, exclusion_reason, recorded_at
        ) VALUES (
            'NIFTY200', 'NSE-ISIN:INE399L01023', 'ATGL', '1234', 'NSE',
            '2020-01-01', '2022-12-31', '2019-12-15', 1.0,
            'CERTIFIED_PIT', NULL, '2020-01-01 00:00:00'
        )
    """)
    # Insert knowledge record
    db.conn.execute("""
        INSERT INTO index_constituent_knowledge (
            universe_name, instrument_id, effective_from, known_at
        ) VALUES (
            'NIFTY200', 'NSE-ISIN:INE399L01023', '2020-01-01', '2019-12-15 18:00:00+00'
        )
    """)
    # Insert historical alias mapping: ADANIGAS -> ATGL
    db.conn.execute("""
        INSERT INTO instrument_aliases (
            canonical_symbol, exchange, provider_name, provider_symbol
        ) VALUES (
            'ATGL', 'NSE', 'HISTORICAL_ALIAS', 'ADANIGAS'
        )
    """)

    # Candle frame with ADANIGAS in 2020 and ATGL in 2021
    candles = pd.DataFrame([
        {"symbol": "ADANIGAS", "timestamp": "2020-06-15 10:00:00", "close": 150.0},
        {"symbol": "ATGL", "timestamp": "2021-06-15 10:00:00", "close": 900.0},
        {"symbol": "UNRELATED", "timestamp": "2020-06-15 10:00:00", "close": 50.0},
    ])

    filtered, _ = filter_frame_by_pit(db, candles, "NIFTY200", required=False)
    # Both ADANIGAS and ATGL candles must be retained
    assert len(filtered) == 2
    matched_symbols = set(filtered["symbol"])
    assert "ADANIGAS" in matched_symbols
    assert "ATGL" in matched_symbols
    assert "UNRELATED" not in matched_symbols
