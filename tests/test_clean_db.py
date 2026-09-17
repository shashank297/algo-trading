from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb

from clean_db import clean_database


class CleanDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_research.duckdb"
        conn = duckdb.connect(str(self.db_path))
        conn.execute("CREATE TABLE strategy_runs (id INT, name VARCHAR);")
        conn.execute("INSERT INTO strategy_runs VALUES (1, 'test_run');")
        conn.execute("CREATE TABLE strategy_metrics (id INT, val FLOAT);")
        conn.execute("INSERT INTO strategy_metrics VALUES (1, 1.25);")
        conn.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_clean_db_dry_run_reports_counts_without_deleting(self) -> None:
        counts = clean_database(self.db_path, dry_run=True, confirm=False)
        self.assertEqual(counts["strategy_runs"], 1)
        self.assertEqual(counts["strategy_metrics"], 1)

        conn = duckdb.connect(str(self.db_path), read_only=True)
        remaining = conn.execute("SELECT COUNT(*) FROM strategy_runs").fetchone()[0]
        conn.close()
        self.assertEqual(remaining, 1)

    def test_clean_db_requires_confirmation(self) -> None:
        with self.assertRaisesRegex(ValueError, "Confirmation required"):
            clean_database(self.db_path, dry_run=False, confirm=False)

    def test_clean_db_deletes_atomically_with_confirmation(self) -> None:
        counts = clean_database(self.db_path, dry_run=False, confirm=True)
        self.assertEqual(counts["strategy_runs"], 1)
        self.assertEqual(counts["strategy_metrics"], 1)

        conn = duckdb.connect(str(self.db_path), read_only=True)
        remaining_runs = conn.execute("SELECT COUNT(*) FROM strategy_runs").fetchone()[0]
        remaining_metrics = conn.execute("SELECT COUNT(*) FROM strategy_metrics").fetchone()[0]
        conn.close()
        self.assertEqual(remaining_runs, 0)
        self.assertEqual(remaining_metrics, 0)
