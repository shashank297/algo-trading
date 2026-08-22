"""Forensic validation tests for Raw Provider Intake Gateway, Multi-Issue Quarantine, and Backfill Failure Isolation."""

from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from data_platform.contracts import (
    DatasetLifecycleStatus,
    PriceAdjustment,
)
from data_platform.service import (
    ingest_raw_provider_dataset,
    recover_incomplete_raw_intakes,
)
from data_platform.source_semantics import SourceSemanticsPolicy
from storage.duckdb_manager import DuckDBManager
from tools.backfill_market_history import _persist_backfill_batch
from trading_stack.pipeline import StrategyPipeline


class TestHistoricalGateway(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = ":memory:"
        self.db = DuckDBManager(self.db_path)
        schema_sql = (Path(__file__).resolve().parent.parent / "database_schema.sql").read_text(encoding="utf-8")
        self.db.conn.execute(schema_sql)

        # Valid 5 daily bars for INFY
        self.bars = pd.DataFrame({
            "timestamp": pd.date_range("2023-01-02", periods=5, freq="D", tz="UTC"),
            "open": [1500.0, 1510.0, 1505.0, 1520.0, 1515.0],
            "high": [1520.0, 1530.0, 1525.0, 1540.0, 1535.0],
            "low": [1490.0, 1500.0, 1495.0, 1510.0, 1505.0],
            "close": [1510.0, 1505.0, 1520.0, 1515.0, 1530.0],
            "volume": [100000.0, 110000.0, 105000.0, 120000.0, 115000.0],
        })

    def test_invalid_provider_bar_is_persisted_before_validation(self) -> None:
        """Malformed OHLC (open=100, high=98, low=95, close=101) is durably saved in raw store, quarantined with row-level issues, and blocked from canonical store."""
        malformed_df = pd.DataFrame([{
            "timestamp": "2026-08-20T09:15:00Z",
            "open": 100.0,
            "high": 98.0,  # Invalid: high < open and high < close
            "low": 95.0,
            "close": 101.0,
            "volume": 1000.0,
        }])

        res = ingest_raw_provider_dataset(
            bars=malformed_df,
            symbol="BAD_SYM",
            exchange="NSE",
            timeframe="1d",
            provider_name="angel_one",
            provider_symbol="BAD_SYM-EQ",
            declared_adjustment=PriceAdjustment.UNADJUSTED,
            db=self.db,
        )

        # 1. Raw result assertions
        self.assertEqual(res.raw_status, DatasetLifecycleStatus.QUARANTINED.value)
        self.assertIsNone(res.canonical_dataset_id)
        self.assertIsNone(res.canonical_status)
        self.assertIsNone(res.bars)
        self.assertIn("HIGH_BELOW_OPEN", res.quarantine_reasons)
        self.assertIn("HIGH_BELOW_CLOSE", res.quarantine_reasons)

        # 2. Raw observations persisted durably
        raw_obs = self.db.conn.execute(
            "SELECT symbol, open_raw, high_raw, close_raw FROM raw_bar_observations WHERE raw_dataset_id = ?",
            [res.raw_dataset_id],
        ).fetchall()
        self.assertEqual(len(raw_obs), 1)
        self.assertEqual(raw_obs[0][0], "BAD_SYM")
        self.assertEqual(raw_obs[0][1], "100.0")
        self.assertEqual(raw_obs[0][2], "98.0")
        self.assertEqual(raw_obs[0][3], "101.0")

        # 3. Quarantine table and issues recorded
        q_row = self.db.conn.execute(
            "SELECT raw_dataset_id, symbol, malformed_row_count FROM historical_market_data_quarantine WHERE raw_dataset_id = ?",
            [res.raw_dataset_id],
        ).fetchone()
        self.assertIsNotNone(q_row)
        self.assertEqual(q_row[1], "BAD_SYM")
        self.assertEqual(q_row[2], 1)

        issues = self.db.conn.execute(
            "SELECT reason_code FROM historical_market_data_quarantine_issues WHERE source_row_number = 0",
        ).fetchall()
        issue_codes = [r[0] for r in issues]
        self.assertIn("HIGH_BELOW_OPEN", issue_codes)
        self.assertIn("HIGH_BELOW_CLOSE", issue_codes)

        # 4. Canonical store is empty for BAD_SYM
        canonical_count = self.db.conn.execute(
            "SELECT COUNT(*) FROM historical_candles WHERE symbol = 'BAD_SYM'",
        ).fetchone()[0]
        self.assertEqual(canonical_count, 0)

    def test_invalid_raw_dataset_never_reaches_canonical_store(self) -> None:
        """Invalid raw dataset is completely excluded from historical_candles."""
        bad_df = pd.DataFrame([{
            "timestamp": "2026-08-20T09:15:00Z",
            "open": 100.0,
            "high": 105.0,
            "low": 110.0,  # Invalid: low > open and low > close
            "close": 102.0,
            "volume": 500.0,
        }])
        res = ingest_raw_provider_dataset(
            bars=bad_df,
            symbol="BAD_LOW",
            exchange="NSE",
            timeframe="1d",
            provider_name="angel_one",
            db=self.db,
        )
        self.assertEqual(res.raw_status, "QUARANTINED")
        self.assertIn("LOW_ABOVE_OPEN", res.quarantine_reasons)
        self.assertIn("LOW_ABOVE_CLOSE", res.quarantine_reasons)

        count = self.db.conn.execute(
            "SELECT COUNT(*) FROM historical_candles WHERE symbol = 'BAD_LOW'",
        ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_quarantined_symbol_does_not_abort_stage1_backfill(self) -> None:
        """In multi-symbol backfill, quarantined symbol is isolated while valid symbols continue and succeed."""
        bad_frame = pd.DataFrame([{
            "timestamp": "2026-08-20T09:15:00Z",
            "open": 100.0, "high": 90.0, "low": 80.0, "close": 95.0, "volume": 1000.0,
        }])
        good_frame_1 = pd.DataFrame([{
            "timestamp": "2026-08-20T09:15:00Z",
            "open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0, "volume": 1000.0,
        }])
        good_frame_2 = pd.DataFrame([{
            "timestamp": "2026-08-20T09:15:00Z",
            "open": 200.0, "high": 210.0, "low": 195.0, "close": 205.0, "volume": 2000.0,
        }])

        d1 = datetime(2026, 8, 19).date()
        d2 = datetime(2026, 8, 20).date()

        # Ingest bad symbol
        count_bad, status_bad = _persist_backfill_batch(
            self.db, [(bad_frame, d1, d2)], "BAD_SYM", "1001", "NSE", "1d",
        )
        self.assertEqual(count_bad, 0)
        self.assertEqual(status_bad, "QUARANTINED")

        # Ingest good symbol 1
        count_g1, status_g1 = _persist_backfill_batch(
            self.db, [(good_frame_1, d1, d2)], "GOOD_SYM_1", "1002", "NSE", "1d",
        )
        self.assertEqual(count_g1, 1)
        self.assertEqual(status_g1, "SUCCESS")

        # Ingest good symbol 2
        count_g2, status_g2 = _persist_backfill_batch(
            self.db, [(good_frame_2, d1, d2)], "GOOD_SYM_2", "1003", "NSE", "1d",
        )
        self.assertEqual(count_g2, 1)
        self.assertEqual(status_g2, "SUCCESS")

        # Verify DB contents
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM historical_candles WHERE symbol = 'BAD_SYM'").fetchone()[0], 0)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM historical_candles WHERE symbol = 'GOOD_SYM_1'").fetchone()[0], 1)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM historical_candles WHERE symbol = 'GOOD_SYM_2'").fetchone()[0], 1)

    def test_raw_ingestion_idempotency_and_replay(self) -> None:
        """Replaying identical malformed payload produces identical raw_hash and deterministic quarantine issues without corrupting state."""
        bad_df = pd.DataFrame([{
            "timestamp": "2026-08-20T09:15:00Z",
            "open": 100.0, "high": 90.0, "low": 80.0, "close": 95.0, "volume": 1000.0,
        }])

        res1 = ingest_raw_provider_dataset(
            bars=bad_df, symbol="REPLAY_SYM", exchange="NSE", timeframe="1d", provider_name="angel_one", db=self.db,
        )
        res2 = ingest_raw_provider_dataset(
            bars=bad_df, symbol="REPLAY_SYM", exchange="NSE", timeframe="1d", provider_name="angel_one", db=self.db,
        )

        self.assertEqual(res1.raw_hash, res2.raw_hash)
        self.assertEqual(res1.quarantine_reasons, res2.quarantine_reasons)
        self.assertNotEqual(res1.raw_dataset_id, res2.raw_dataset_id)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM historical_candles WHERE symbol = 'REPLAY_SYM'").fetchone()[0], 0)

    def test_corrected_provider_retrieval_can_promote_without_mutating_prior_quarantine(self) -> None:
        """When provider returns corrected data after quarantine, new data is promoted to canonical store while prior quarantine evidence remains intact."""
        bad_df = pd.DataFrame([{
            "timestamp": "2026-08-20T09:15:00Z",
            "open": 100.0, "high": 90.0, "low": 80.0, "close": 95.0, "volume": 1000.0,
        }])
        good_df = pd.DataFrame([{
            "timestamp": "2026-08-20T09:15:00Z",
            "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": 1000.0,
        }])

        res_bad = ingest_raw_provider_dataset(
            bars=bad_df, symbol="CORRECT_SYM", exchange="NSE", timeframe="1d", provider_name="angel_one", db=self.db,
        )
        self.assertEqual(res_bad.raw_status, "QUARANTINED")

        res_good = ingest_raw_provider_dataset(
            bars=good_df, symbol="CORRECT_SYM", exchange="NSE", timeframe="1d", provider_name="angel_one", db=self.db,
        )
        self.assertEqual(res_good.raw_status, "STRUCTURALLY_VALID")
        self.assertIsNotNone(res_good.canonical_dataset_id)

        # Prior quarantine evidence is preserved
        q_count = self.db.conn.execute(
            "SELECT COUNT(*) FROM historical_market_data_quarantine WHERE raw_dataset_id = ?",
            [res_bad.raw_dataset_id],
        ).fetchone()[0]
        self.assertEqual(q_count, 1)

        # Canonical store now contains corrected data
        c_count = self.db.conn.execute(
            "SELECT COUNT(*) FROM historical_candles WHERE symbol = 'CORRECT_SYM'",
        ).fetchone()[0]
        self.assertEqual(c_count, 1)

    def test_quarantined_dataset_unreachable_by_research_and_strategy_apis(self) -> None:
        """Quarantined datasets cannot be loaded by StrategyPipeline.load_candles or research workflows."""
        bad_df = pd.DataFrame([{
            "timestamp": "2026-08-20T09:15:00Z",
            "open": 100.0, "high": 90.0, "low": 80.0, "close": 95.0, "volume": 1000.0,
        }])
        ingest_raw_provider_dataset(
            bars=bad_df, symbol="UNREACHABLE_SYM", exchange="NSE", timeframe="1d", provider_name="angel_one", db=self.db,
        )

        pipeline = StrategyPipeline(self.db, require_authoritative_certification=False)
        with self.assertRaises(ValueError):
            pipeline.load_candles("UNREACHABLE_SYM", "1d")

    def test_raw_persistence_accepts_unparseable_provider_values(self) -> None:
        """Raw persistence does not throw DB cast exceptions on string garbage ('N/A', inf, missing timestamps); raw values survive in raw_bar_observations."""
        unparseable_rows = [
            {
                "timestamp": "GARBAGE_TS",
                "open": "N/A",
                "high": "--",
                "low": -10.0,
                "close": "null",
                "volume": float("inf"),
            }
        ]
        res = ingest_raw_provider_dataset(
            bars=unparseable_rows,
            symbol="GARBAGE_SYM",
            exchange="NSE",
            timeframe="1d",
            provider_name="angel_one",
            db=self.db,
        )
        self.assertEqual(res.raw_status, "QUARANTINED")
        self.assertIn("TIMESTAMP_INVALID", res.quarantine_reasons)
        self.assertIn("NUMERIC_PARSE_FAILED", res.quarantine_reasons)

        # Check raw_bar_observations preserved the exact strings
        raw_row = self.db.conn.execute(
            "SELECT timestamp_raw, open_raw, high_raw FROM raw_bar_observations WHERE raw_dataset_id = ?",
            [res.raw_dataset_id],
        ).fetchone()
        self.assertIsNotNone(raw_row)
        self.assertEqual(raw_row[0], "GARBAGE_TS")
        self.assertEqual(raw_row[1], "N/A")
        self.assertEqual(raw_row[2], "--")

    def test_crash_after_raw_commit_is_recoverable(self) -> None:
        """If a process crashes while a dataset is stranded in 'RAW_RECORDED', recover_incomplete_raw_intakes reconciles it to its terminal state."""
        # Manually create a stranded RAW_RECORDED dataset with raw rows
        raw_id = "stranded-dataset-999"
        self.db.conn.execute(
            """
            INSERT INTO market_datasets (
                dataset_id, dataset_stage, symbol, exchange, timeframe,
                provider_name, provider_symbol, provider_token, declared_adjustment,
                lifecycle_status, raw_hash, row_count
            ) VALUES (?, 'RAW', 'STRANDED_SYM', 'NSE', '1d', 'angel_one', 'STRANDED_SYM', '999', 'UNADJUSTED', 'RAW_RECORDED', 'hash123', 1)
            """,
            [raw_id],
        )
        self.db.conn.execute(
            """
            INSERT INTO raw_bar_observations (
                raw_dataset_id, source_row_number, symbol, exchange, timeframe,
                provider_name, timestamp_raw, open_raw, high_raw, low_raw, close_raw, volume_raw,
                raw_row_json, retrieved_at
            ) VALUES (?, 0, 'STRANDED_SYM', 'NSE', '1d', 'angel_one', '2026-08-20T09:15:00Z', '100.0', '105.0', '95.0', '102.0', '1000.0', '{"source_row_number": 0, "timestamp": "2026-08-20T09:15:00Z", "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": 1000.0}', CURRENT_TIMESTAMP)
            """,
            [raw_id],
        )

        recovered = recover_incomplete_raw_intakes(self.db)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].raw_status, "STRUCTURALLY_VALID")
        self.assertIsNotNone(recovered[0].canonical_dataset_id)

    def test_structurally_valid_but_semantically_blocked_dataset_never_promotes(self) -> None:
        """A structurally valid dataset that fails source semantics admission (e.g. contract conflict) has canonical_dataset_id=None and is not stored in historical_candles."""
        # Insert corporate action with 2:1 split for SPLIT_SYM
        self.db.conn.execute(
            """
            INSERT INTO corporate_actions (action_id, symbol, exchange, action_type, ex_date, share_multiplier, source)
            VALUES ('ca-1', 'SPLIT_SYM', 'NSE', 'SPLIT', '2023-01-04', 2.0, 'NSE_TEST')
            """
        )
        # Create unadjusted bars across ex_date without the 2.0x price jump (empirically already split-adjusted)
        bars = pd.DataFrame({
            "timestamp": pd.date_range("2023-01-02", periods=5, freq="D", tz="UTC"),
            "open": [100.0, 101.0, 100.5, 102.0, 101.5],
            "high": [102.0, 103.0, 102.5, 104.0, 103.5],
            "low": [99.0, 100.0, 99.5, 101.0, 100.5],
            "close": [101.0, 100.5, 102.0, 101.5, 103.0],
            "volume": [1000.0, 1100.0, 1050.0, 1200.0, 1150.0],
        })

        # Strict fail-closed policy
        import warnings
        from data_platform.source_semantics import CorporateActionBasisWarning
        policy = SourceSemanticsPolicy(fail_closed=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", CorporateActionBasisWarning)
            res = ingest_raw_provider_dataset(
                bars=bars,
                symbol="SPLIT_SYM",
                exchange="NSE",
                timeframe="1d",
                provider_name="angel_one",
                declared_adjustment=PriceAdjustment.UNADJUSTED,  # Contradicts empirical split-adjusted data
                policy=policy,
                db=self.db,
            )

        self.assertEqual(res.raw_status, "STRUCTURALLY_VALID")
        self.assertIsNone(res.canonical_dataset_id)
        self.assertEqual(res.canonical_status, "CONTRACT_CONFLICT")
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM historical_candles WHERE symbol = 'SPLIT_SYM'").fetchone()[0], 0)

    def test_quarantine_parent_issues_and_status_update_are_atomic(self) -> None:
        """Atomic quarantine recording ensures parent record, issue records, and market_datasets status match exactly."""
        bad_df = pd.DataFrame([{
            "timestamp": "2026-08-20T09:15:00Z",
            "open": 100.0, "high": 90.0, "low": 80.0, "close": 95.0, "volume": 1000.0,
        }])
        res = ingest_raw_provider_dataset(
            bars=bad_df, symbol="ATOMIC_SYM", exchange="NSE", timeframe="1d", provider_name="angel_one", db=self.db,
        )
        status = self.db.conn.execute(
            "SELECT lifecycle_status FROM market_datasets WHERE dataset_id = ?",
            [res.raw_dataset_id],
        ).fetchone()[0]
        self.assertEqual(status, "QUARANTINED")

        q_parent = self.db.conn.execute(
            "SELECT COUNT(*) FROM historical_market_data_quarantine WHERE raw_dataset_id = ?",
            [res.raw_dataset_id],
        ).fetchone()[0]
        self.assertEqual(q_parent, 1)

        q_issues = self.db.conn.execute(
            "SELECT COUNT(*) FROM historical_market_data_quarantine_issues WHERE quarantine_id IN (SELECT quarantine_id FROM historical_market_data_quarantine WHERE raw_dataset_id = ?)",
            [res.raw_dataset_id],
        ).fetchone()[0]
        self.assertGreater(q_issues, 0)


if __name__ == "__main__":
    unittest.main()
