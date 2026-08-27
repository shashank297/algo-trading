"""CLI integration tests for market-regime command in research.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from research import main


def test_cli_market_regime_eod(capsys):
    """Test research.py CLI with --command market-regime in EOD mode."""
    test_argv = [
        "--command",
        "market-regime",
        "--context",
        "EOD",
        "--as-of",
        "2026-08-27",
    ]

    with patch("research.DuckDBManager") as mock_db_cls:
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        # Mock historical candles df empty to produce valid INSUFFICIENT_CONTEXT snapshot without crash
        import pandas as pd
        mock_db.conn.execute.return_value.df.return_value = pd.DataFrame()

        exit_code = main(test_argv)
        assert exit_code == 0

        captured = capsys.readouterr()
        output_json = json.loads(captured.out)
        assert output_json["market"] == "NSE"
        assert output_json["context_type"] == "EOD"
        assert output_json["as_of"] == "2026-08-27"
        assert "raw_regime" in output_json
        assert "confidence" in output_json
        assert "trend_score" in output_json
        assert "volatility_score" in output_json
        assert "breadth_score" in output_json
        assert "input_evidence_hash" in output_json


def test_cli_market_regime_intraday(capsys):
    """Test research.py CLI with --command market-regime in INTRADAY mode with explicit decision-time."""
    test_argv = [
        "--command",
        "market-regime",
        "--context",
        "INTRADAY",
        "--as-of",
        "2026-08-27",
        "--decision-time",
        "2026-08-27T10:00:00+05:30",
    ]

    with patch("research.DuckDBManager") as mock_db_cls:
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        import pandas as pd
        mock_db.conn.execute.return_value.df.return_value = pd.DataFrame()

        exit_code = main(test_argv)
        assert exit_code == 0

        captured = capsys.readouterr()
        output_json = json.loads(captured.out)
        assert output_json["context_type"] == "INTRADAY"
        assert output_json["decision_time"] == "2026-08-27T10:00:00+05:30"
        assert "raw_regime" in output_json
