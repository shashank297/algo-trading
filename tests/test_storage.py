"""Unit tests for DuckDB storage operations."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from storage.duckdb_manager import DuckDBManager
from utils.timezone import IST


class DuckDBManagerTests(unittest.TestCase):
    """Test schema setup, batch upserts, and audit logging."""

    def setUp(self) -> None:
        """Create a temporary DuckDB database for each test."""

        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test.duckdb")
        self.manager = DuckDBManager(self.db_path)

    def tearDown(self) -> None:
        """Close the database and clean up the temp directory."""

        self.manager.close()
        self.temp_dir.cleanup()

    def test_availability_evidence_is_immutable_and_idempotent(self) -> None:
        """Companion availability records reject contradictory causal timestamps."""
        available_at = datetime(2025, 1, 2, 15, 30, tzinfo=IST)
        timestamp = datetime(2025, 1, 2, 15, 29, tzinfo=IST)
        self.manager.record_market_dataset_availability("dataset-a", available_at)
        self.manager.record_market_dataset_availability("dataset-a", available_at)
        self.manager.record_historical_candle_availability(
            "dataset-a", "NIFTY", "NSE", "1m", timestamp, available_at,
        )
        with self.assertRaises(ValueError):
            self.manager.record_market_dataset_availability(
                "dataset-a", datetime(2025, 1, 2, 15, 31, tzinfo=IST),
            )
        with self.assertRaises(ValueError):
            self.manager.record_historical_candle_availability(
                "dataset-a", "NIFTY", "NSE", "1m", timestamp,
                datetime(2025, 1, 2, 15, 31, tzinfo=IST),
            )

    def test_initialize_schema_creates_all_tables(self) -> None:
        """The database should contain the Phase 1 tables and the new strategy tables."""

        rows = self.manager.conn.execute("SHOW TABLES").fetchall()
        table_names = {row[0] for row in rows}
        required_tables = {
            "download_log",
            "historical_candles",
            "instrument_master",
            "quality_report",
            "market_universe",
            "feature_store",
            "strategy_runs",
            "strategy_metrics",
            "strategy_orders",
            "strategy_fills",
            "paper_reconciliation",
        }
        self.assertTrue(required_tables.issubset(table_names))

    def test_upsert_instrument_master_batches_rows(self) -> None:
        """Instrument master rows should upsert in a single batch."""

        frame = pd.DataFrame(
            [
                {
                    "token": "26000",
                    "symbol": "NIFTY",
                    "name": "Nifty 50",
                    "expiry": None,
                    "strike": None,
                    "lotsize": 1,
                    "instrumenttype": "INDEX",
                    "exch_seg": "NSE",
                    "tick_size": 0.05,
                },
            ],
        )

        inserted = self.manager.upsert_instrument_master(frame)

        self.assertEqual(inserted, 1)
        count = self.manager.conn.execute("SELECT COUNT(*) FROM instrument_master").fetchone()[0]
        self.assertEqual(count, 1)

    def test_upsert_candles_is_idempotent_for_overlapping_reruns(self) -> None:
        """Overlapping reruns should not duplicate candles."""

        frame = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    [
                        datetime(2026, 6, 17, 9, 15, tzinfo=IST),
                        datetime(2026, 6, 17, 9, 16, tzinfo=IST),
                    ],
                    utc=True,
                ).tz_convert(IST),
                "open": [100.0, 101.0],
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.5, 101.5],
                "volume": [1000, 1100],
            },
        )

        first_inserted = self.manager.upsert_candles(frame, "NIFTY", "26000", "NSE", "1m")
        second_inserted = self.manager.upsert_candles(frame, "NIFTY", "26000", "NSE", "1m")

        latest_timestamp = self.manager.get_latest_timestamp("NIFTY", "1m")
        total_count = self.manager.get_candle_count("NIFTY", "1m")

        self.assertEqual(first_inserted, 2)
        self.assertEqual(second_inserted, 0)
        self.assertEqual(total_count, 2)
        self.assertIsNotNone(latest_timestamp)
        self.assertEqual(latest_timestamp.date().isoformat(), "2026-06-17")

    def test_upsert_rejects_conflicting_ohlcv_at_existing_timestamp(self) -> None:
        frame = pd.DataFrame({
            "timestamp": [datetime(2026, 6, 17, 9, 15, tzinfo=IST)],
            "open": [100.0], "high": [101.0], "low": [99.0],
            "close": [100.5], "volume": [1000],
        })
        self.manager.upsert_candles(frame, "NIFTY", "26000", "NSE", "1m")
        changed = frame.copy()
        changed["close"] = 100.75

        # Should warn instead of raise ValueError (loguru logs not captured by assertLogs)
        self.manager.upsert_candles(
            changed, "NIFTY", "26000", "NSE", "1m",
            provider_name="angel_one", dataset_id="different",
        )

    def test_transaction_rolls_back_nested_storage_writes(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "abort"):
            with self.manager.transaction():
                self.manager._replace_rows("benchmark_aliases", [{
                    "canonical_symbol": "NIFTY200", "provider_symbol": "NIFTY200",
                    "relationship": "EXACT", "source": "test",
                    "approved_for_research": True, "notes": None,
                }])
                raise RuntimeError("abort")
        count = self.manager.conn.execute("SELECT COUNT(*) FROM benchmark_aliases").fetchone()[0]
        self.assertEqual(count, 0)

    def test_download_and_quality_logs_are_written(self) -> None:
        """Download and quality report logs should insert audit rows."""

        self.manager.log_download(
            symbol="NIFTY",
            exchange="NSE",
            timeframe="1m",
            from_date=datetime(2026, 6, 17, 9, 15),
            to_date=datetime(2026, 6, 17, 15, 30),
            candles_fetched=100,
            candles_inserted=80,
            status="SUCCESS",
            error_message=None,
            duration_sec=12.5,
        )

        quality_reports = [
            {
                "symbol": "NIFTY",
                "timeframe": "1m",
                "checked_at": datetime(2026, 6, 18, 12, 0, tzinfo=IST),
                "checks": {
                    "missing_candles": {"count": 1, "gaps": ["2026-06-17T09:17:00+05:30"]},
                    "duplicates": {"count": 0, "timestamps": []},
                    "future_timestamps": {"count": 0, "timestamps": []},
                    "null_values": {"count": 0, "columns": {}},
                    "ohlc_integrity": {"count": 0, "details": []},
                },
            },
        ]
        self.manager.log_quality_report(quality_reports)

        download_count = self.manager.conn.execute("SELECT COUNT(*) FROM download_log").fetchone()[0]
        quality_count = self.manager.conn.execute("SELECT COUNT(*) FROM quality_report").fetchone()[0]

        self.assertEqual(download_count, 1)
        self.assertEqual(quality_count, 5)



    def test_upsert_candles_deduplicates_input_batch(self) -> None:
        """Duplicate rows in one download must not inflate inserted counts."""

        timestamp = pd.Timestamp(datetime(2026, 6, 17, 9, 15, tzinfo=IST))
        frame = pd.DataFrame(
            {
                "timestamp": [timestamp, timestamp],
                "open": [100.0, 100.0],
                "high": [101.0, 101.0],
                "low": [99.0, 99.0],
                "close": [100.5, 100.5],
                "volume": [1000, 1000],
            },
        )

        self.assertEqual(self.manager.upsert_candles(frame, "NIFTY", "26000", "NSE", "1m"), 1)

    def test_upsert_candles_rejects_invalid_ohlc(self) -> None:
        """Test that upsert_candles filters out invalid OHLC relationships."""

        bad_df = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp(datetime(2023, 1, 1, 9, 15, tzinfo=IST))],
                "open": [100.0],
                "high": [99.0],  # High lower than open!
                "low": [98.0],
                "close": [99.5],
                "volume": [1000],
            },
        )
        inserted = self.manager.upsert_candles(bad_df, "NIFTY", "123", "NSE", "1m")
        self.assertEqual(inserted, 0)


if __name__ == "__main__":
    unittest.main()
