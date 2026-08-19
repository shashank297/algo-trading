"""Tests for shared human and structured operational logging."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from utils import LoggerSetup


class ObservabilityTests(unittest.TestCase):
    def test_structured_log_contains_operation_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            logger = LoggerSetup.setup({
                "logging": {
                    "path": directory, "level": "INFO", "rotation": "1 day",
                    "retention": "1 day",
                },
            }, component="test", command="verify", operation_id="operation-123")
            logger.info("structured_event test_value={}", 7)
            path = next(Path(directory).glob("events_*.jsonl"))
            record = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])["record"]
            logger.remove()

        self.assertEqual(record["extra"]["operation_id"], "operation-123")
        self.assertEqual(record["extra"]["component"], "test")
        self.assertIn("structured_event", record["message"])


if __name__ == "__main__":
    unittest.main()
