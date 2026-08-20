"""Test-only helper utilities for explicitly constructing synthetic test fixtures."""

from __future__ import annotations

import pandas as pd

from storage.duckdb_manager import DuckDBManager


def insert_synthetic_candles_unchecked(
    db: DuckDBManager,
    bars: pd.DataFrame,
    symbol: str,
    token: str = "1",
    exchange: str = "NSE",
    timeframe: str = "1d",
    adjustment: str = "SPLIT_ADJUSTED",
    provider_name: str = "synthetic_test",
    dataset_id: str | None = None,
) -> int:
    """Explicit test-only helper to insert synthetic candles without running through the admission gateway."""
    return db.upsert_candles(
        bars=bars,
        symbol=symbol,
        token=token,
        exchange=exchange,
        timeframe=timeframe,
        adjustment=adjustment,
        provider_name=provider_name,
        dataset_id=dataset_id,
    )
