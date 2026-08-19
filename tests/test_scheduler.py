from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scheduler import advance_active_paper_sessions, run_job
from storage import DuckDBManager


class SchedulerTests(unittest.TestCase):
    def test_no_active_paper_sessions_is_a_successful_noop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "scheduler.duckdb"
            db = DuckDBManager(str(database))
            db.close()
            result = advance_active_paper_sessions({
                "database": {"path": str(database)},
                "research": {"indian_delivery_costs": {}},
            })
        self.assertEqual(result, [])

    def test_ingestion_failure_never_advances_paper(self) -> None:
        config = {
            "operations": {
                "ingestion_universe_snapshot": "TEST",
                "benchmark": "NIFTY200",
                "paper_after_ingestion": True,
            }
        }
        with patch("scheduler.load_runtime_config", return_value=config), patch(
            "scheduler.main", return_value=1,
        ) as ingestion, patch("scheduler.advance_active_paper_sessions") as advance:
            run_job()
        ingestion.assert_called_once_with([
            "--universe-snapshot", "TEST", "--benchmark", "NIFTY200",
        ])
        advance.assert_not_called()


if __name__ == "__main__":
    unittest.main()
