"""Tests for the canonical Historical Ground-Truth Admission Gateway."""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from data_platform.contracts import DatasetSnapshot, Instrument, PriceAdjustment
from data_platform.service import admit_and_promote_dataset
from data_platform.source_semantics import SourceValidationStatus
from storage.duckdb_manager import DuckDBManager
from tools.revalidate_historical_datasets import revalidate_datasets


class TestHistoricalGateway(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = ":memory:"
        self.db = DuckDBManager(self.db_path)
        schema_sql = (Path(__file__).resolve().parent.parent / "database_schema.sql").read_text(encoding="utf-8")
        self.db.conn.execute(schema_sql)

        # 5 daily bars for INFY
        self.bars = pd.DataFrame({
            "timestamp": pd.date_range("2023-01-02", periods=5, freq="D", tz="UTC"),
            "open": [1500.0, 1510.0, 1505.0, 1520.0, 1515.0],
            "high": [1520.0, 1530.0, 1525.0, 1540.0, 1535.0],
            "low": [1490.0, 1500.0, 1495.0, 1510.0, 1505.0],
            "close": [1510.0, 1505.0, 1520.0, 1515.0, 1530.0],
            "volume": [100000.0, 110000.0, 105000.0, 120000.0, 115000.0],
        })
        self.snapshot = DatasetSnapshot.from_bars(
            instrument=Instrument(
                canonical_symbol="INFY",
                exchange="NSE",
                provider_name="angel_one",
                provider_symbol="INFY-EQ",
                currency="INR",
                timezone="Asia/Kolkata",
            ),
            timeframe="1d",
            bars=self.bars,
            adjustment=PriceAdjustment.UNADJUSTED,
            timezone_name="Asia/Kolkata",
        )

    def test_admit_and_promote_dataset_raw_persisted_on_ca_failure(self) -> None:
        """Raw dataset is persisted even if corporate actions query or adjustment step fails."""
        broken_db = DuckDBManager(":memory:")
        # Drop corporate_actions table on broken_db to force CA lookup failure
        broken_db.conn.execute("DROP TABLE corporate_actions")
        with self.assertRaises(RuntimeError):
            admit_and_promote_dataset(snapshot=self.snapshot, db=broken_db)

        # But the raw dataset must be durably recorded in market_datasets
        raw_row = broken_db.conn.execute(
            "SELECT dataset_id, canonical_symbol FROM market_datasets WHERE dataset_id = ?",
            [self.snapshot.dataset_id],
        ).fetchone()
        self.assertIsNotNone(raw_row)
        self.assertEqual(raw_row[1], "INFY")

    def test_admit_and_promote_dataset_idempotent(self) -> None:
        """Admit and promote run twice produces identical semantics_hash without double adjustment."""
        # First promotion
        res1 = admit_and_promote_dataset(
            snapshot=self.snapshot,
            db=self.db,
            target_adjustment=PriceAdjustment.SPLIT_ADJUSTED,
        )
        self.assertEqual(res1.status, SourceValidationStatus.VERIFIED)
        self.assertIsNotNone(res1.bars)

        # Second promotion on same snapshot
        res2 = admit_and_promote_dataset(
            snapshot=self.snapshot,
            db=self.db,
            target_adjustment=PriceAdjustment.SPLIT_ADJUSTED,
        )
        self.assertEqual(res1.semantics_hash, res2.semantics_hash)
        pd.testing.assert_frame_equal(res1.bars, res2.bars)

    def test_legacy_dataset_requires_revalidation_before_canonical_use(self) -> None:
        """Legacy dataset with unverified cache can be revalidated by the migration utility."""
        self.db.upsert_candles(
            self.bars,
            symbol="TCS",
            token="11536",
            exchange="NSE",
            timeframe="1d",
            adjustment="UNADJUSTED",
            provider_name="angel_one",
            dataset_id="legacy-ds-123",
        )
        report = revalidate_datasets(self.db)
        tcs_report = report[report["symbol"] == "TCS"]
        self.assertFalse(tcs_report.empty)
        self.assertEqual(tcs_report["validation_status"].iloc[0], "VERIFIED")
        self.assertTrue(tcs_report["is_admitted"].iloc[0])


if __name__ == "__main__":
    unittest.main()
