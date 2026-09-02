"""Fail-closed orchestration tests for the canonical research pipeline."""

from __future__ import annotations

from pathlib import Path

import run_pipeline


def _config(tmp_path: Path, *, live_trading: bool = False) -> dict:
    return {
        "database": {"path": str(tmp_path / "research.duckdb")},
        "data": {"start_date": "2012-01-01"},
        "research": {
            "live_trading": live_trading,
            "indian_delivery_costs": {"version": "test"},
            "risk": {
                "max_position_pct": 0.05,
                "max_gross_exposure_pct": 0.20,
                "max_daily_loss_pct": 0.01,
                "max_drawdown_pct": 0.05,
                "max_sector_exposure_pct": 0.40,
                "max_open_positions": 20,
                "max_var_pct": 0.02,
                "min_liquidity_crore": 0.0,
            },
        },
    }


def test_database_failure_blocks_pit_and_downstream(monkeypatch, tmp_path):
    calls: list[str] = []
    monkeypatch.setattr(
        run_pipeline,
        "_database_preflight",
        lambda path: ({"database_path": str(path)}, ("DATABASE_RECOVERY_REQUIRED",)),
    )
    monkeypatch.setattr(run_pipeline, "_pit_preflight", lambda *args, **kwargs: calls.append("pit"))

    result = run_pipeline.run_preflight(
        _config(tmp_path), universe_snapshot="PIT", database_path=None
    )

    assert not result.ready
    assert "DATABASE_RECOVERY_REQUIRED" in result.blockers
    assert "PIT_UNIVERSE_NOT_READY" in result.blockers
    assert calls == []


def test_wal_failure_blocks_all_downstream_stages(monkeypatch, tmp_path):
    stages: list[str] = []
    monkeypatch.setattr(run_pipeline, "_load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(run_pipeline, "validate_config", lambda config: None)
    monkeypatch.setattr(
        run_pipeline,
        "run_preflight",
        lambda *args, **kwargs: run_pipeline.PreflightResult(
            False, {"database_open": False}, ("DATABASE_RECOVERY_REQUIRED",)
        ),
    )
    monkeypatch.setattr(run_pipeline, "run_step", lambda command, description: stages.append(description) or 0)

    assert run_pipeline.main(["--universe-snapshot", "PIT", "--skip-api"]) == 2
    assert stages == []


def test_survivorship_biased_universe_blocks_backfill_and_research(monkeypatch, tmp_path):
    stages: list[str] = []
    monkeypatch.setattr(run_pipeline, "_load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(run_pipeline, "validate_config", lambda config: None)
    monkeypatch.setattr(
        run_pipeline,
        "run_preflight",
        lambda *args, **kwargs: run_pipeline.PreflightResult(
            False,
            {"selected_universe": "NIFTY200_2026_08_17", "survivorship_bias": True},
            ("PIT_UNIVERSE_NOT_READY", "SURVIVORSHIP_BIASED_UNIVERSE"),
        ),
    )
    monkeypatch.setattr(run_pipeline, "run_step", lambda command, description: stages.append(description) or 0)

    assert run_pipeline.main(["--universe-snapshot", "NIFTY200_2026_08_17"]) == 2
    assert stages == []


def test_missing_pit_coverage_blocks_readiness(monkeypatch, tmp_path):
    monkeypatch.setattr(
        run_pipeline,
        "_database_preflight",
        lambda path: ({"database_open": True}, ()),
    )
    monkeypatch.setattr(
        run_pipeline,
        "_pit_preflight",
        lambda *args, **kwargs: ({"selected_universe": "PIT"}, ("PIT_UNIVERSE_NOT_READY", "PIT_COVERAGE_UNAVAILABLE")),
    )

    result = run_pipeline.run_preflight(
        _config(tmp_path), universe_snapshot="PIT", database_path=None
    )

    assert not result.ready
    assert "PIT_COVERAGE_UNAVAILABLE" in result.blockers


def test_preflight_only_runs_no_mutating_stages(monkeypatch, tmp_path):
    stages: list[str] = []
    monkeypatch.setattr(run_pipeline, "_load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(run_pipeline, "validate_config", lambda config: None)
    monkeypatch.setattr(
        run_pipeline,
        "run_preflight",
        lambda *args, **kwargs: run_pipeline.PreflightResult(True, {"database_open": True}, ()),
    )
    monkeypatch.setattr(run_pipeline, "run_step", lambda command, description: stages.append(description) or 0)

    assert run_pipeline.main(["--universe-snapshot", "PIT", "--preflight-only"]) == 0
    assert stages == []


def test_valid_pipeline_uses_exact_order_and_snapshot(monkeypatch, tmp_path):
    stages: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(run_pipeline, "_load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(run_pipeline, "validate_config", lambda config: None)
    monkeypatch.setattr(
        run_pipeline,
        "run_preflight",
        lambda *args, **kwargs: run_pipeline.PreflightResult(True, {}, ()),
    )
    monkeypatch.setattr(
        run_pipeline,
        "run_step",
        lambda command, description: stages.append((description, command)) or 0,
    )

    assert run_pipeline.main(["--universe-snapshot", "PIT", "--skip-api"]) == 0
    assert [description for description, _ in stages] == [
        "Incremental Market Data Backfill",
        "Data Quality & Session Guardrails",
        "Mass Strategy Backtesting & Evaluation",
    ]
    assert all(command[command.index("--universe-snapshot") + 1] == "PIT" for _, command in stages)


def test_backfill_failure_blocks_quality_and_research(monkeypatch, tmp_path):
    stages: list[str] = []
    monkeypatch.setattr(run_pipeline, "_load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(run_pipeline, "validate_config", lambda config: None)
    monkeypatch.setattr(
        run_pipeline,
        "run_preflight",
        lambda *args, **kwargs: run_pipeline.PreflightResult(True, {}, ()),
    )
    monkeypatch.setattr(
        run_pipeline,
        "run_step",
        lambda command, description: stages.append(description) or 7,
    )

    assert run_pipeline.main(["--universe-snapshot", "PIT"]) == 7
    assert stages == ["Incremental Market Data Backfill"]


def test_data_quality_failure_blocks_research(monkeypatch, tmp_path):
    stages: list[str] = []
    monkeypatch.setattr(run_pipeline, "_load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(run_pipeline, "validate_config", lambda config: None)
    monkeypatch.setattr(
        run_pipeline,
        "run_preflight",
        lambda *args, **kwargs: run_pipeline.PreflightResult(True, {}, ()),
    )
    results = iter((0, 9))
    monkeypatch.setattr(
        run_pipeline,
        "run_step",
        lambda command, description: stages.append(description) or next(results),
    )

    assert run_pipeline.main(["--universe-snapshot", "PIT"]) == 9
    assert stages == [
        "Incremental Market Data Backfill",
        "Data Quality & Session Guardrails",
    ]


def test_post_ingestion_failure_blocks_research(monkeypatch, tmp_path):
    stages: list[str] = []
    monkeypatch.setattr(run_pipeline, "_load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(run_pipeline, "validate_config", lambda config: None)
    results = iter((run_pipeline.PreflightResult(True, {}, ()), run_pipeline.PreflightResult(False, {}, ("DQ_NOT_CERTIFIED",))))
    monkeypatch.setattr(run_pipeline, "run_preflight", lambda *args, **kwargs: next(results))
    monkeypatch.setattr(run_pipeline, "run_step", lambda command, description: stages.append(description) or 0)

    assert run_pipeline.main(["--universe-snapshot", "PIT"]) == 2
    assert stages == [
        "Incremental Market Data Backfill",
        "Data Quality & Session Guardrails",
    ]


def test_live_trading_fails_campaign_baseline_gate(tmp_path):
    details, blockers = run_pipeline._baseline_preflight(_config(tmp_path, live_trading=True), mode="event-driven")

    assert details["execution_mode"] == "event-driven"
    assert "LIVE_TRADING_MUST_BE_FALSE" in blockers


def test_skip_api_does_not_launch_dashboard(monkeypatch, tmp_path):
    stages: list[str] = []
    monkeypatch.setattr(run_pipeline, "_load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(run_pipeline, "validate_config", lambda config: None)
    monkeypatch.setattr(
        run_pipeline,
        "run_preflight",
        lambda *args, **kwargs: run_pipeline.PreflightResult(True, {}, ()),
    )
    monkeypatch.setattr(run_pipeline, "run_step", lambda command, description: stages.append(description) or 0)
    monkeypatch.setattr(run_pipeline.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("API launched")))

    assert run_pipeline.main(["--universe-snapshot", "PIT", "--skip-api"]) == 0
    assert stages[-1] == "Mass Strategy Backtesting & Evaluation"


def test_successful_research_launches_api_last(monkeypatch, tmp_path):
    stages: list[str] = []
    subprocess_calls: list[list[str]] = []
    monkeypatch.setattr(run_pipeline, "_load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(run_pipeline, "validate_config", lambda config: None)
    monkeypatch.setattr(
        run_pipeline,
        "run_preflight",
        lambda *args, **kwargs: run_pipeline.PreflightResult(True, {}, ()),
    )
    monkeypatch.setattr(run_pipeline, "run_step", lambda command, description: stages.append(description) or 0)
    monkeypatch.setattr(
        run_pipeline.subprocess,
        "run",
        lambda command, **kwargs: subprocess_calls.append(command) or type("Result", (), {"returncode": 0})(),
    )

    assert run_pipeline.main(["--universe-snapshot", "PIT"]) == 0
    assert stages[-1] == "Mass Strategy Backtesting & Evaluation"
    assert subprocess_calls[-1][1:4] == ["-m", "uvicorn", "tools.dashboard.api.main:app"]
