from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from storage import DuckDBManager
from validators.duckdb_quality import DuckDBValidator
from validators.severity import summarize_quality


class QualitySeverityTests(unittest.TestCase):
    def test_anomaly_is_warning_not_page(self) -> None:
        checks = {
            "anomalies": {"count": 3},
            "duplicates": {"count": 0},
            "missing_candles": {"count": 0},
        }
        summary = summarize_quality(checks)
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["status"], "WARNING")
        self.assertFalse(summary["page_operator"])

    def test_integrity_failure_pages_and_missing_data_fails_closed(self) -> None:
        summary = summarize_quality({"ohlc_integrity": {"count": 1}})
        self.assertFalse(summary["passed"])
        self.assertTrue(summary["page_operator"])
        with tempfile.TemporaryDirectory() as directory:
            db = DuckDBManager(str(Path(directory) / "empty.duckdb"))
            try:
                report = DuckDBValidator("1d").run_all_checks(db, "MISSING")
            finally:
                db.close()
        self.assertFalse(report["passed"])
        self.assertEqual(report["status"], "ERROR")

    def test_check_failed_status_always_critical_and_pages(self) -> None:
        """When a check crashes with CHECK_FAILED, severity is overridden to CRITICAL and pages operator."""
        checks = {
            "session_alignment": {"status": "CHECK_FAILED", "count": 0, "error": "Query timeout"},
            "duplicates": {"count": 0},
        }
        summary = summarize_quality(checks)
        self.assertFalse(summary["passed"])
        self.assertEqual(summary["status"], "CRITICAL")
        self.assertTrue(summary["page_operator"])
        self.assertTrue(summary["has_check_failure"])
        self.assertEqual(checks["session_alignment"]["severity"], "CRITICAL")
        self.assertFalse(checks["session_alignment"]["check_executed"])


if __name__ == "__main__":
    unittest.main()
