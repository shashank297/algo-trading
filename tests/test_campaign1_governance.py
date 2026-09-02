from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from experiments.statistical_tests import _aggregate_campaign_root_evidence, resolve_authoritative_dsr
from experiments.trials import ExperimentFamilySpec, ResearchTrial, TrialStatus
from storage.duckdb_manager import DuckDBManager
from research import materialize_campaign_1_configurations
from data_platform.universe import PointInTimeConstituent, PointInTimeUniverseManager
from trading_stack.datasets import filter_frame_by_pit


CAMPAIGN_FAMILY = "campaign-1-2d653914799e"


def _family(maximum_trials: int = 2) -> ExperimentFamilySpec:
    return ExperimentFamilySpec(
        experiment_family_id=CAMPAIGN_FAMILY,
        hypothesis="Campaign 1 governance test",
        strategy_names=["test_strategy"],
        strategy_versions=["1.0.0"],
        universe_snapshot_id="TEST",
        timeframe="1d",
        feature_versions=["features-v1"],
        cost_model_version="test-costs",
        parameter_space={},
        maximum_trials=maximum_trials,
        selection_metric="sharpe",
        walk_forward_design={},
        source_revision="test",
    )


def _trial(parameters: dict[str, int], *, parent_trial_id: str | None = None) -> ResearchTrial:
    return ResearchTrial(
        experiment_family_id=CAMPAIGN_FAMILY,
        strategy_name="test_strategy",
        strategy_version="1.0.0",
        scope="SINGLE_ASSET",
        timeframe="1d",
        parameters=parameters,
        source_revision="test",
        data_hash="resolved-data",
        cost_model_hash="cost-hash",
        frame_certification_id="frame-cert",
        parent_trial_id=parent_trial_id,
        status=TrialStatus.PLANNED,
    )


def test_campaign_materializer_has_exact_deterministic_root_identities() -> None:
    first = materialize_campaign_1_configurations()
    second = materialize_campaign_1_configurations()

    assert first == second
    assert len(first) == 74
    assert len({entry["root_trial_id"] for entry in first}) == 74
    assert all(entry["parameter_hash"] for entry in first)


def test_campaign_children_do_not_consume_root_budget(tmp_path: Path) -> None:
    db = DuckDBManager(str(tmp_path / "campaign.duckdb"))
    try:
        db.register_experiment_family(_family())
        root_a = db.create_research_trial(_trial({"p": 1}))
        root_b = db.create_research_trial(_trial({"p": 2}))
        child = _trial({"p": 1}, parent_trial_id=root_a).model_copy(update={"symbol": "AAA"})
        assert db.create_research_trial(child)
        with pytest.raises(RuntimeError, match="budget exhausted"):
            db.create_research_trial(_trial({"p": 3}))
        with pytest.raises(ValueError, match="valid root"):
            db.create_research_trial(_trial({"p": 4}, parent_trial_id="missing-root"))
        assert root_b
    finally:
        db.close()


def test_campaign_dsr_counts_roots_not_symbol_or_fold_children() -> None:
    roots: list[dict[str, object]] = []
    for index in range(74):
        roots.append({
            "trial_id": f"root-{index}",
            "parent_trial_id": None,
            "strategy_name": "strategy",
            "strategy_version": "1.0.0",
            "timeframe": "1d",
            "parameters": {"p": index},
            "status": "SUCCEEDED",
            "metrics": {"sharpe": 0.5 + index / 1000},
        })
    children: list[dict[str, object]] = [
        {
            "trial_id": f"child-{index}",
            "parent_trial_id": f"root-{index % 74}",
            "strategy_name": "strategy",
            "strategy_version": "1.0.0",
            "timeframe": "1d",
            "parameters": {"p": index % 74},
            "status": "SUCCEEDED",
            "metrics": {"sharpe": 0.5},
        }
        for index in range(500)
    ]

    class Registry:
        @staticmethod
        def list_research_trials(*, family_id: str) -> list[dict[str, object]]:
            assert family_id == CAMPAIGN_FAMILY
            return [*roots, *children]

    result = resolve_authoritative_dsr(
        Registry(),
        np.sin(np.arange(40, dtype=float)),
        CAMPAIGN_FAMILY,
        minimum_observations=30,
    )

    assert result.effective_trials == 74
    assert result.total_trials == 74
    assert len(result.trial_ids) == 74


def test_campaign_pit_known_at_is_causal_and_inclusive(tmp_path: Path) -> None:
    db = DuckDBManager(str(tmp_path / "pit-known-at.duckdb"))
    try:
        PointInTimeUniverseManager.insert_constituent(
            db,
            PointInTimeConstituent(
                universe_name="NIFTY200",
                symbol="AAA",
                token="1",
                instrument_id="NSE:AAA:EQ",
                exchange="NSE",
                effective_from=date(2020, 1, 1),
                known_from=date(2020, 1, 1),
                known_at=datetime(2020, 1, 2, 10, 0, tzinfo=timezone.utc),
            ),
        )
        frame = pd.DataFrame(
            {
                "symbol": ["AAA", "AAA"],
                "timestamp": [
                    pd.Timestamp("2020-01-02 09:59:59", tz="UTC"),
                    pd.Timestamp("2020-01-02 10:00:00", tz="UTC"),
                ],
            }
        )
        filtered, pit_hash = filter_frame_by_pit(db, frame, "NIFTY200", required=True)
        assert pit_hash
        assert filtered["timestamp"].tolist() == [pd.Timestamp("2020-01-02 10:00:00", tz="UTC")]
    finally:
        db.close()


def test_campaign_root_retry_is_rejected(tmp_path: Path) -> None:
    db = DuckDBManager(str(tmp_path / "campaign-retry.duckdb"))
    try:
        db.register_experiment_family(_family(maximum_trials=2))
        root = _trial({"p": 11})
        assert db.create_research_trial(root) == root.trial_id
        with pytest.raises(ValueError, match="root configuration has already been attempted"):
            db.create_research_trial(root)
    finally:
        db.close()


def test_campaign_root_evidence_aggregates_all_children_in_stable_order() -> None:
    root = {"trial_id": "root", "status": "PLANNED"}
    children = [
        {"trial_id": "child-b", "status": "SUCCEEDED", "metrics": {"sharpe": 3.0, "run_id": "b"}},
        {"trial_id": "child-a", "status": "SUCCEEDED", "metrics": {"sharpe": 1.0, "run_id": "a"}},
    ]
    aggregate = _aggregate_campaign_root_evidence(root, children)
    assert aggregate["status"] == "SUCCEEDED"
    assert aggregate["metrics"]["sharpe"] == 2.0
    assert aggregate["child_trial_ids"] == ["child-a", "child-b"]
