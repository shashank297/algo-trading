import pandas as pd
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

import research
from trading_stack.datasets import filter_frame_by_pit


@pytest.mark.parametrize("universe_name", [None, "", "CONFIGURED_UNIVERSE", "CUSTOM"])
def test_required_pit_filter_rejects_missing_universe_scope(universe_name):
    frame = pd.DataFrame({"timestamp": ["2022-01-03T09:15:00+05:30"]})

    with pytest.raises(ValueError, match="PIT universe scope is required"):
        filter_frame_by_pit(None, frame, universe_name, required=True)


def test_optional_pit_filter_keeps_unscoped_frame_unchanged():
    frame = pd.DataFrame({"timestamp": ["2022-01-03T09:15:00+05:30"]})

    filtered, pit_hash = filter_frame_by_pit(None, frame, None, required=False)

    assert filtered.equals(frame)
    assert pit_hash is None


def test_authoritative_single_symbol_cli_passes_selected_pit_snapshot(monkeypatch, capsys):
    config = {"database": {"path": ":memory:"}, "research": {"risk": {}}}
    monkeypatch.setattr(research, "load_yaml", lambda path: ([{"symbol": "RELIANCE", "instrument_type": "EQUITY"}]
                          if str(path).endswith("symbols.yaml") else config))
    monkeypatch.setattr(research, "apply_env_overrides", lambda value: value)
    monkeypatch.setattr(research, "validate_config", lambda _config: None)
    monkeypatch.setattr(research, "validate_symbols", lambda value: value)
    monkeypatch.setattr(research.LoggerSetup, "setup", lambda *args, **kwargs: MagicMock())
    monkeypatch.setattr(research, "configured_nse_calendar", lambda _config: None)
    monkeypatch.setattr(research, "build_risk_engine", lambda _config: object())
    monkeypatch.setattr(research, "load_universe_snapshot_symbols", lambda *_args: [{"symbol": "RELIANCE"}])

    class FakeDatabase:
        def close(self):
            pass

    class FakePipeline:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, **kwargs):
            captured.update(kwargs)
            metrics = SimpleNamespace()
            result = SimpleNamespace(
                run_id="run-test", strategy_name=kwargs["strategy_name"], symbol=kwargs["symbol"],
                timeframe=kwargs["timeframe"], mode=kwargs["mode"], metrics=metrics, orders=[], fills=[],
                equity_curve=pd.DataFrame({"equity": [100_000.0]}),
            )
            return {"result": result}

    captured = {}
    monkeypatch.setattr(research, "DuckDBManager", lambda *_args, **_kwargs: FakeDatabase())
    monkeypatch.setattr(research, "StrategyPipeline", FakePipeline)
    monkeypatch.setattr(research, "UniverseResearchService", lambda *_args, **_kwargs: object())

    assert research.main([
        "--command", "backtest", "--mode", "event-driven", "--symbol", "RELIANCE",
        "--universe-snapshot", "NIFTY200_PIT",
    ]) == 0
    assert captured["universe_snapshot_id"] == "NIFTY200_PIT"
