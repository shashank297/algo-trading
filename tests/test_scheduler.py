from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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

    def test_scheduler_injects_authoritative_risk_engine(self) -> None:
        config = {
            "database": {"path": "scheduler.duckdb"},
            "research": {
                "risk": {"max_position_pct": 0.05, "max_gross_exposure_pct": 0.20},
                "indian_delivery_costs": {},
            },
        }
        with patch("scheduler.DuckDBManager") as manager, patch("scheduler.StrategyPipeline") as pipeline, patch(
            "scheduler.build_risk_engine", return_value="authoritative-engine",
        ) as build_engine:
            manager.return_value.conn.execute.return_value.fetchall.return_value = [
                ("SINGLE", "sess", "run", "strategy", "ABC", "1d", "{}", 100_000.0, None, None),
            ]
            pipeline.return_value.run_paper_session.return_value = {
                "forward_result": SimpleNamespace(status="PROCESSED", processed_bars=1),
            }
            advance_active_paper_sessions(config)
        build_engine.assert_called_once_with(config)
        self.assertEqual(pipeline.call_args.kwargs["risk_engine"], "authoritative-engine")


if __name__ == "__main__":
    unittest.main()
