from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from experiments.statistical_tests import resolve_authoritative_dsr
from experiments.trials import ExperimentFamilySpec, ResearchTrial, TrialStatus
from storage.duckdb_manager import DuckDBManager
from research import materialize_campaign_1_configurations


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
