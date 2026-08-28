"""CLI integration tests for market-regime command in research.py."""

from __future__ import annotations

import json
import pandas as pd
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from research import main


def _empty_regime_bars_result() -> dict:
    """Return the canonical empty result from load_regime_bars for mocking."""
    return {
        "bars": pd.DataFrame(),
        "dataset_id": None,
        "content_hash": None,
        "cutoff_applied": "2026-08-27T15:30:00+05:30",
    }


def test_cli_market_regime_rejects_configured_universe() -> None:
    """Historical regime evaluation must not read today's configured membership."""
    with patch("research.validate_config", return_value=None), patch("research.DuckDBManager"):
        with pytest.raises(ValueError, match="authoritative PIT universe identity"):
            main(["--command", "market-regime", "--universe-snapshot", "CONFIGURED_UNIVERSE"])


def test_cli_market_regime_rejects_explicit_universe_override() -> None:
    """Regime breadth must always derive from the complete authoritative PIT universe."""
    with patch("research.validate_config", return_value=None), patch("research.DuckDBManager"):
        with pytest.raises(ValueError, match="--universe is not permitted"):
            main([
                "--command", "market-regime", "--universe-snapshot", "TEST_PIT",
                "--universe", "TEST",
            ])


def test_cli_market_regime_eod(capsys):
    """Test research.py CLI with --command market-regime in EOD mode."""
    test_argv = [
        "--command",
        "market-regime",
        "--context",
        "EOD",
        "--as-of",
        "2026-08-27",
        "--universe-snapshot",
        "TEST_PIT",
    ]

    with patch("research.validate_config", return_value=None), patch("research.DuckDBManager") as mock_db_cls, patch(
        "research.PointInTimeUniverseManager.get_constituents", return_value=[SimpleNamespace(symbol="TEST")],
    ):
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_db.get_regime_transition_state.return_value = None
        mock_db.get_operational_risk_state.return_value = None
        # Mock load_regime_bars to return empty certified result (produces INSUFFICIENT_CONTEXT)
        mock_db.load_regime_bars.return_value = _empty_regime_bars_result()

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
        assert output_json["operational_regime"] == "UNINITIALIZED"
        assert output_json["hysteresis"]["decision"] == "INSUFFICIENT_CONTEXT"
        assert output_json["stress_state"]["state"] == "NORMAL"
        mock_db.persist_regime_transition.assert_called_once()


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
        "--universe-snapshot",
        "TEST_PIT",
    ]

    with patch("research.validate_config", return_value=None), patch("research.DuckDBManager") as mock_db_cls, patch(
        "research.PointInTimeUniverseManager.get_constituents", return_value=[SimpleNamespace(symbol="TEST")],
    ):
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_db.get_regime_transition_state.return_value = None
        mock_db.get_operational_risk_state.return_value = None
        mock_db.load_regime_bars.return_value = {
            "bars": pd.DataFrame(),
            "dataset_id": None,
            "content_hash": None,
            "cutoff_applied": "2026-08-27T10:00:00+05:30",
        }

        exit_code = main(test_argv)
        assert exit_code == 0

        captured = capsys.readouterr()
        output_json = json.loads(captured.out)
        assert output_json["context_type"] == "INTRADAY"
        assert output_json["decision_time"] == "2026-08-27T10:00:00+05:30"
        assert "raw_regime" in output_json
        assert output_json["operational_regime"] == "UNINITIALIZED"
        assert output_json["hysteresis"]["decision"] == "INSUFFICIENT_CONTEXT"
        mock_db.persist_regime_transition.assert_called_once()
