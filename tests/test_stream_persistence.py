"""Unit tests for asynchronous single-writer DuckDBStreamWriter persistence."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from data_platform.contracts import LiveTickerMode, LtpTick
from trading_stack.domain import AssetClass, Bar
from trading_stack.stream_persistence import DuckDBStreamWriter


class TestDuckDBStreamWriter(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_stream.duckdb")
        self.writer = DuckDBStreamWriter(
            db_path=self.db_path,
            batch_size=5,
            flush_interval_seconds=0.2,
        )
        self.writer.start()

    def tearDown(self) -> None:
        self.writer.stop()
        self.temp_dir.cleanup()

    def test_batch_flush_and_persistence_of_ticks_and_bars(self) -> None:
        # Enqueue 5 ticks to trigger batch flush
        for i in range(5):
            tick = LtpTick(
                exchange="NSE_CM",
                token=str(1000 + i),
                symbol=f"SYM_{i}",
                mode=LiveTickerMode.LTP,
                exchange_timestamp=datetime(2026, 8, 20, 9, 15, i, tzinfo=timezone.utc),
                received_at_utc=datetime(2026, 8, 20, 9, 15, i, tzinfo=timezone.utc),
                received_monotonic_ns=i * 1000,
                raw_packet_size=51,
                sequence_number=i + 1,
                ltp=100.0 + i,
            )
            self.writer.enqueue_tick(tick)

        # Enqueue bar
        bar = Bar(

            timestamp=pd.Timestamp("2026-08-20 09:15:00", tz="UTC"),
            open=100.0,
            high=105.0,
            low=99.0,
            close=104.0,
            volume=5000.0,
            symbol="RELIANCE-EQ",
            timeframe="1m",
            exchange="NSE_CM",
            asset_class=AssetClass.INDIA_EQUITY,
        )
        self.writer.enqueue_bar(bar, timeframe="1m")

        # Stop writer to trigger final flush and close the DuckDB connection cleanly
        self.writer.stop()

        # Read back from DuckDB
        conn = duckdb.connect(self.db_path)
        ticks_df = conn.execute("SELECT * FROM market_ticks ORDER BY sequence_number").df()
        self.assertEqual(len(ticks_df), 5)
        self.assertEqual(ticks_df["token"].iloc[0], "1000")
        self.assertEqual(ticks_df["ltp"].iloc[4], 104.0)

        bars_df = conn.execute("SELECT * FROM market_bars").df()
        conn.close()

        self.assertEqual(len(bars_df), 1)
        self.assertEqual(bars_df["symbol"].iloc[0], "RELIANCE-EQ")
        self.assertEqual(bars_df["close"].iloc[0], 104.0)

    def test_persistence_health_lifecycle(self) -> None:
        """Writer tracks HEALTHY when running, STOPPED when shut down."""
        from trading_stack.stream_persistence import PersistenceHealth

        self.assertEqual(self.writer.health, PersistenceHealth.HEALTHY)
        self.writer.stop()
        self.assertEqual(self.writer.health, PersistenceHealth.STOPPED)

    def test_stream_dead_letter_fsync_on_forced_spool(self) -> None:
        """Dead letter spool writes JSONL file durably with fsync on overflow."""
        from trading_stack.stream_persistence import PersistenceHealth

        records = [
            {"token": "3045", "exchange": "NSE_CM", "sequence_number": 1, "exchange_timestamp": "2026-08-20T09:15:00Z", "ltp": 600.0}
        ]
        self.writer._spool_dead_letter("tick", records)
        self.assertEqual(self.writer.health, PersistenceHealth.UNSAFE)

        spool_files = list(Path("data/spool/stream").glob("stream_dead_letter_*.jsonl"))
        self.assertTrue(len(spool_files) >= 1)


if __name__ == "__main__":
    unittest.main()
