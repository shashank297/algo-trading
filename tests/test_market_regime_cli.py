"""CLI integration tests for market-regime command in research.py."""

from __future__ import annotations

import json
from copy import deepcopy
import pandas as pd
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from research import PROJECT_ROOT, load_yaml, main


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


def test_cli_intraday_stress_uses_current_session_certified_bars_only(capsys) -> None:
    """Emergency stress uses current-session intraday evidence, never synthetic daily bars."""
    config = deepcopy(load_yaml(str(PROJECT_ROOT / "config" / "config.example.yaml")))
    config["research"]["regime_transition"] = {
        "stress_override_enabled": True,
        "stress_thresholds": {"benchmark_loss_caution": 0.02, "benchmark_loss_stress": 0.05},
    }
    daily = pd.DataFrame([
        {"timestamp": "2026-08-25T15:30:00+05:30", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1_000},
        {"timestamp": "2026-08-26T15:30:00+05:30", "open": 101.0, "high": 102.0, "low": 100.0, "close": 100.0, "volume": 1_000},
    ])
    intraday = pd.DataFrame([
        {"timestamp": "2026-08-27T09:16:00+05:30", "open": 99.0, "high": 100.0, "low": 98.0, "close": 99.0, "volume": 100},
        {"timestamp": "2026-08-27T09:20:00+05:30", "open": 99.0, "high": 100.0, "low": 93.0, "close": 94.0, "volume": 100},
    ])

    def result(bars: pd.DataFrame) -> dict:
        return {"bars": bars, "dataset_id": "certified", "content_hash": "hash", "certification_id": "dq", "timeframe": "1m", "cutoff_applied": "2026-08-27T10:00:00+05:30"}

    with patch("research.load_yaml", side_effect=[config, {"symbols": [{"symbol": "TEST", "token": "1", "exchange": "NSE", "instrument_type": "EQUITY"}]}]), patch(
        "research.validate_config", return_value=None
    ), patch("research.DuckDBManager") as mock_db_cls, patch(
        "research.PointInTimeUniverseManager.get_constituents", return_value=[SimpleNamespace(symbol="TEST")],
    ):
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_db.get_regime_transition_state.return_value = None
        mock_db.get_operational_risk_state.return_value = None
        mock_db.load_regime_bars.side_effect = [result(daily), result(intraday)] + [result(pd.DataFrame())] * 4 + [result(daily)]
        assert main(["--command", "market-regime", "--context", "INTRADAY", "--as-of", "2026-08-27", "--decision-time", "2026-08-27T10:00:00+05:30", "--universe-snapshot", "TEST_PIT"]) == 0
        transition = mock_db.persist_regime_transition.call_args.args[1]
        assert transition.risk_event.stress_evidence is not None
        assert transition.risk_event.stress_evidence.benchmark_loss == pytest.approx(0.06)
        assert transition.risk_event.stress_evidence.extreme_gap == pytest.approx(0.01)
        assert transition.risk_state.risk_state.value == "STRESS"
        assert json.loads(capsys.readouterr().out)["raw_regime"] == "INSUFFICIENT_CONTEXT"
