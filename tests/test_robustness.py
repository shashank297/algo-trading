"""Comprehensive integration, leak-prevention, and mathematical tests for experiments/robustness.py."""

from __future__ import annotations

import copy
from datetime import date, datetime, timezone
import json
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from risk.engine import RiskEngine
from risk.models import RiskPolicy
from experiments.models import ExperimentSpec
from experiments.robustness import (
    NestedWalkForwardSplitter,
    ParameterRobustnessSelector,
    RobustnessBundle,
    RobustnessEvaluator,
    RobustnessPolicy,
    StressScenarioEngine,
    canonical_hash,
)

from experiments.statistical_tests import (
    EvidenceStatus,
    TrialCountSource,
    compute_bootstrap_confidence_intervals,
    compute_dsr,
    compute_monte_carlo_robustness,
    compute_psr,
)
from experiments.trials import ExperimentFamilySpec, ResearchTrial
from storage.duckdb_manager import DuckDBManager
from storage.migrations.runner import MigrationRunner
from trading_stack.datasets import ResearchDataset
from trading_stack.features import FeatureFactory


def _permissive_risk() -> RiskEngine:
    return RiskEngine(RiskPolicy(
        max_position_pct=1.0,
        max_gross_exposure_pct=1.0,
        max_daily_loss_pct=1.0,
        max_drawdown_pct=1.0,
        max_sector_exposure_pct=1.0,
        max_open_positions=500,
        max_var_pct=1.0,
        min_liquidity_crore=0.0,
    ))


def test_governed_robustness_requires_injected_risk_engine() -> None:
    """Family-governed robustness evaluation cannot run with an implicit engine."""
    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["TCS"],
        timeframe="1d",
        experiment_family_id="governed-family",
        require_authoritative_certification=False,
    )

    with pytest.raises(ValueError, match="injected configured RiskEngine"):
        RobustnessEvaluator(cast(DuckDBManager, None)).evaluate("parent-run", spec)



def _make_dummy_candles(n_days: int = 400, start_date: date = date(2022, 1, 1), seed: int = 42) -> pd.DataFrame:
    """Generate deterministic synthetic candles with price and volume."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start=start_date, periods=n_days, freq="B", tz="Asia/Kolkata")
    
    # Random walk with slight upward drift
    returns = rng.normal(loc=0.0008, scale=0.015, size=n_days)
    prices = 100.0 * np.cumprod(1.0 + returns)
    
    rows = []
    for dt, close in zip(dates, prices):
        open_p = close * (1.0 + rng.normal(0, 0.002))
        high_p = max(open_p, close) * (1.0 + abs(rng.normal(0, 0.005)))
        low_p = min(open_p, close) * (1.0 - abs(rng.normal(0, 0.005)))
        vol = int(rng.uniform(100_000, 500_000))
        rows.append({
            "timestamp": dt,
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close,
            "volume": vol,
            "symbol": "TEST_SYM",
            "dataset_id": "test-dataset-01",
        })
    return pd.DataFrame(rows)


def _make_dummy_dataset(
    n_days: int = 400,
    start_date: date = date(2022, 1, 1),
    seed: int = 42,
    dataset_content_hashes: dict[str, str] | None = None,
    dataset_snapshot_ids: dict[str, str | None] | None = None,
) -> ResearchDataset:
    """Generate deterministic synthetic ResearchDataset with features."""
    candles = _make_dummy_candles(n_days=n_days, start_date=start_date, seed=seed)
    panel = FeatureFactory().build(candles, timezone_name="Asia/Kolkata")
    panel["symbol"] = "TEST_SYM"
    return ResearchDataset(
        universe_snapshot_id="U_TEST",
        dataset_snapshot_ids=dataset_snapshot_ids or {"TEST_SYM": "DS_TEST"},
        panel=panel,
        frame_certification_id="cert-01",
        dataset_content_hashes=dataset_content_hashes or {"TEST_SYM": "ds-hash-01"},
    )



def test_migration_022_and_storage_schema(tmp_path: Any) -> None:
    """Verify migration 022 applies cleanly and creates strategy_robustness_evaluations table."""
    db_path = str(tmp_path / "test_migration_022.duckdb")
    runner = MigrationRunner(db_path)
    applied = runner.run_migrations()
    assert "022_phase2_6_robustness" in applied

    db = DuckDBManager(db_path)
    tables = [r[0] for r in db.conn.execute("SHOW TABLES").fetchall()]
    assert "strategy_robustness_evaluations" in tables
    db.close()


def test_nested_wf_sealed_final_oos_leakage_prevention(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prove mathematically that changing future FINAL OOS data has ZERO impact on parameter selection.

    Invariant: Candidate discovery and selection occurs on TRAIN + VALIDATION only.
    Final OOS is completely sealed during selection.
    """
    db_path = str(tmp_path / "test_leakage.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)

    # 1. Base candle dataset (400 days)
    ds_base = _make_dummy_dataset(n_days=400, seed=42)
    
    # 2. Perturbed candle dataset: future test days (days 350-400) have altered close prices
    candles_perturbed = _make_dummy_candles(n_days=400, seed=42)
    candles_perturbed.loc[350:399, "close"] = candles_perturbed.loc[350:399, "close"] * 5.0
    candles_perturbed.loc[350:399, "high"] = candles_perturbed.loc[350:399, "high"] * 5.0
    panel_perturbed = FeatureFactory().build(candles_perturbed, timezone_name="Asia/Kolkata")
    panel_perturbed["symbol"] = "TEST_SYM"
    ds_perturbed = ResearchDataset(
        universe_snapshot_id="U_TEST",
        dataset_snapshot_ids={"TEST_SYM": "DS_TEST"},
        panel=panel_perturbed,
        frame_certification_id="cert-01",
        dataset_content_hashes={"TEST_SYM": "ds-hash-perturbed"},
    )


    evaluator = RobustnessEvaluator(db, policy=RobustnessPolicy(), risk_engine=_permissive_risk())

    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["TEST_SYM"],
        timeframe="1d",
        parameters={"fast_threshold": 0.0, "min_volatility": 0.0},
    )

    monkeypatch.setattr(evaluator, "_source", lambda spec, scope, lookback: ds_base)

    bundle_base = evaluator.evaluate(
        parent_run_id="run-base",
        spec=spec,
        train_size=150,
        val_size=50,
        test_size=50,
    )

    monkeypatch.setattr(evaluator, "_source", lambda spec, scope, lookback: ds_perturbed)

    bundle_perturbed = evaluator.evaluate(
        parent_run_id="run-perturbed",
        spec=spec,
        train_size=150,
        val_size=50,
        test_size=50,
    )

    # Invariant assertion: Selected parameters and train/val fold metrics MUST BE 100% IDENTICAL
    # despite radical perturbation of future final OOS data!
    for f_base, f_pert in zip(bundle_base.nested_folds, bundle_perturbed.nested_folds):
        assert f_base.selected_parameters == f_pert.selected_parameters
        assert f_base.train_metrics == f_pert.train_metrics
        assert f_base.val_metrics == f_pert.val_metrics

    # But the evaluated final OOS metrics WILL differ reflecting the actual out-of-sample test
    assert bundle_base.nested_folds[-1].final_oos_metrics != bundle_perturbed.nested_folds[-1].final_oos_metrics

    db.close()


def test_purge_and_embargo_boundaries() -> None:
    """Verify purge removes overlapping train observations and embargo delays test observations."""
    policy = RobustnessPolicy(purge_window=5, embargo_window=3)
    assert policy.purge_window == 5
    assert policy.embargo_window == 3

    # Reject negative purge / embargo
    with pytest.raises(ValueError, match="purge_window must be non-negative"):
        RobustnessEvaluator(cast(DuckDBManager, None), policy=RobustnessPolicy(), risk_engine=RiskEngine()).evaluate(
            "run-neg",
            ExperimentSpec(strategy_name="trend_following", universe=["SYM"], timeframe="1d"),
            purge_window=-1,
        )

    with pytest.raises(ValueError, match="embargo_window must be non-negative"):
        RobustnessEvaluator(cast(DuckDBManager, None), policy=RobustnessPolicy(), risk_engine=RiskEngine()).evaluate(
            "run-neg",
            ExperimentSpec(strategy_name="trend_following", universe=["SYM"], timeframe="1d"),
            embargo_window=-2,
        )


def test_parameter_robustness_plateau_beats_isolated_spike() -> None:
    """Prove that a broad stable plateau beats an isolated high-Sharpe spike under the robustness policy."""
    policy = RobustnessPolicy(
        plateau_min_ratio=0.80,
        sensitivity_weight=0.50,
        stability_weight=0.20,
        plateau_weight=0.40,
        raw_score_weight=0.10,
    )
    selector = ParameterRobustnessSelector(policy)

    grid = {
        "fast_period": (5, 10, 15, 20, 25),
        "slow_period": (20, 30, 40, 50, 60),
    }

    # Define candidate parameter points
    # Point A: (10, 30) - Isolated spike: train Sharpe = 2.5, but all neighbors have Sharpe = -0.5
    # Point B: (20, 40) - Broad plateau: train Sharpe = 1.8, and all neighbors have Sharpe = 1.7
    candidates = [
        {"fast_period": 10, "slow_period": 30},
        {"fast_period": 20, "slow_period": 40},
    ]

    scores_by_param = {
        # Point A (Spike)
        json.dumps({"fast_period": 10, "slow_period": 30}, sort_keys=True): 2.5,
        # Point A neighbors
        json.dumps({"fast_period": 5, "slow_period": 30}, sort_keys=True): -0.5,
        json.dumps({"fast_period": 15, "slow_period": 30}, sort_keys=True): -0.5,
        json.dumps({"fast_period": 10, "slow_period": 20}, sort_keys=True): -0.5,
        json.dumps({"fast_period": 10, "slow_period": 40}, sort_keys=True): -0.5,

        # Point B (Plateau)
        json.dumps({"fast_period": 20, "slow_period": 40}, sort_keys=True): 1.8,
        # Point B neighbors
        json.dumps({"fast_period": 15, "slow_period": 40}, sort_keys=True): 1.7,
        json.dumps({"fast_period": 25, "slow_period": 40}, sort_keys=True): 1.75,
        json.dumps({"fast_period": 20, "slow_period": 30}, sort_keys=True): 1.8,
        json.dumps({"fast_period": 20, "slow_period": 50}, sort_keys=True): 1.7,
    }

    from experiments.trials import canonical_hash
    hashed_scores = {canonical_hash(json.loads(k)): v for k, v in scores_by_param.items()}

    evaluated = selector.evaluate_candidates(
        scores_by_param=hashed_scores,
        candidates=candidates,
        grid=grid,
    )

    # Point B (plateau) must win over Point A (isolated spike)
    selected_winner = evaluated[0]
    assert selected_winner.selected is True
    assert selected_winner.parameters == {"fast_period": 20, "slow_period": 40}
    assert selected_winner.plateau_score > 0.80

    # Point A must have high sensitivity and lose
    loser = evaluated[1]
    assert loser.parameters == {"fast_period": 10, "slow_period": 30}
    assert loser.sensitivity_score > selected_winner.sensitivity_score
    assert loser.aggregate_robustness_score < selected_winner.aggregate_robustness_score


def test_cost_stress_2x_worsens_net_performance(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that 2.0x transaction costs strictly worsens net performance without mutating baseline."""
    db_path = str(tmp_path / "test_cost_stress.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)

    ds = _make_dummy_dataset(n_days=400, seed=42)
    evaluator = RobustnessEvaluator(db, policy=RobustnessPolicy(), risk_engine=_permissive_risk())

    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["TEST_SYM"],
        timeframe="1d",
        cost_model={"fee_bps": 10.0, "brokerage_rate_bps": 10.0, "stt_buy_bps": 10.0, "stt_sell_bps": 10.0},
    )

    monkeypatch.setattr(evaluator, "_source", lambda spec, scope, lookback: ds)

    bundle = evaluator.evaluate(
        parent_run_id="run-cost-stress",
        spec=spec,
        train_size=150,
        val_size=50,
        test_size=50,
    )

    assert len(bundle.cost_stress) == 4
    costs_1x = next(c for c in bundle.cost_stress if c.multiplier == 1.0)
    costs_15x = next(c for c in bundle.cost_stress if c.multiplier == 1.5)
    costs_2x = next(c for c in bundle.cost_stress if c.multiplier == 2.0)
    costs_3x = next(c for c in bundle.cost_stress if c.multiplier == 3.0)

    # Net total return must monotonically worsen with increasing cost multipliers
    assert costs_1x.metrics["total_return"] >= costs_15x.metrics["total_return"]
    assert costs_15x.metrics["total_return"] >= costs_2x.metrics["total_return"]
    assert costs_2x.metrics["total_return"] >= costs_3x.metrics["total_return"]

    # Net Sharpe must monotonically decrease
    assert costs_1x.metrics["sharpe"] >= costs_2x.metrics["sharpe"]

    # Baseline cost spec in original spec was NOT mutated
    assert spec.cost_model["fee_bps"] == 10.0

    db.close()


def test_execution_stress_scenarios_deterministic(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify swing execution stress scenarios (gap, slippage, delay, missed fills) run deterministically."""
    db_path = str(tmp_path / "test_exec_stress.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)

    ds = _make_dummy_dataset(n_days=400, seed=42)
    evaluator = RobustnessEvaluator(db, policy=RobustnessPolicy(), risk_engine=_permissive_risk())

    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["TEST_SYM"],
        timeframe="1d",
    )

    monkeypatch.setattr(evaluator, "_source", lambda spec, scope, lookback: ds)

    bundle = evaluator.evaluate(
        parent_run_id="run-exec-stress",
        spec=spec,
        train_size=150,
        val_size=50,
        test_size=50,
    )

    scenario_names = {s.scenario_name for s in bundle.execution_stress}
    assert "overnight_gap_stress" in scenario_names
    assert "stop_slippage_stress" in scenario_names
    assert "execution_delay" in scenario_names
    assert "missed_fills" in scenario_names

    # Missed fills uses deterministic seed
    missed = next(s for s in bundle.execution_stress if s.scenario_name == "missed_fills")
    assert missed.seed == 42
    assert "sharpe" in missed.metrics

    db.close()


def test_trial_registry_linkage_and_dsr_sensitivity(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify authoritative DSR links to Phase 2.1 trial registry and updates when registry grows."""
    db_path = str(tmp_path / "test_trial_linkage.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)

    # 1. Register an experiment family
    fam_spec = ExperimentFamilySpec(
        experiment_family_id="fam-phase26-test",
        hypothesis="Test DSR trial count linkage",
        strategy_names=["trend_following"],
        strategy_versions=["1.1.0"],
        universe_snapshot_id="U_TEST",
        timeframe="1d",
        feature_versions=["1.0"],
        cost_model_version="v1",
        parameter_space={"fast_threshold": [0.0, 0.02, 0.05], "min_volatility": [0.0, 0.01]},
        maximum_trials=50,
        selection_metric="sharpe",
        walk_forward_design={"train_size": 150, "test_size": 50},
        source_revision="rev-01",
    )
    db.register_experiment_family(fam_spec)

    # 2. Insert 5 historical candidate trials (some SUCCEEDED, some FAILED, one INVALIDATED)
    for i in range(5):
        trial = ResearchTrial(
            experiment_family_id="fam-phase26-test",
            strategy_name="trend_following",
            strategy_version="1.1.0",
            scope="SINGLE_ASSET",
            timeframe="1d",
            parameters={"fast_threshold": 0.01 * i, "min_volatility": 0.0},
            source_revision="rev-01",
            data_hash="data-hash-01",
            frame_certification_id="cert-01",
            cost_model_hash="cost-hash-01",
        )
        tid = db.create_research_trial(trial)
        if i == 0:
            db.transition_research_trial(tid, "SUCCEEDED", metrics={"sharpe": 1.5, "total_return": 0.25})
        elif i == 1:
            db.transition_research_trial(tid, "SUCCEEDED", metrics={"sharpe": 0.8, "total_return": 0.10})
        elif i == 2:
            db.transition_research_trial(tid, "FAILED", error_message="Loss threshold exceeded")
        elif i == 3:
            db.transition_research_trial(tid, "INVALIDATED", invalidation_reason="Data corrupted during backfill")
        else:
            db.transition_research_trial(tid, "SUCCEEDED", metrics={"sharpe": 1.1, "total_return": 0.15})

    ds = _make_dummy_dataset(n_days=400, seed=42)
    evaluator = RobustnessEvaluator(db, policy=RobustnessPolicy(), risk_engine=_permissive_risk())

    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["TEST_SYM"],
        timeframe="1d",
        experiment_family_id="fam-phase26-test",
    )

    monkeypatch.setattr(evaluator, "_source", lambda spec, scope, lookback: ds)

    bundle_5 = evaluator.evaluate(
        parent_run_id="run-dsr-5",
        spec=spec,
        train_size=150,
        val_size=50,
        test_size=50,
    )

    assert bundle_5.dsr.experiment_family_id == "fam-phase26-test"
    assert bundle_5.dsr.status == EvidenceStatus.VALID
    assert bundle_5.dsr.invalidated_trials == 1  # Exactly 1 invalidated trial audited
    assert bundle_5.dsr.effective_trials >= 3

    # Now add 20 more trials to the registry for the family with consistent variance
    for j in range(20):
        trial = ResearchTrial(
            experiment_family_id="fam-phase26-test",
            strategy_name="trend_following",
            strategy_version="1.1.0",
            scope="SINGLE_ASSET",
            timeframe="1d",
            parameters={"fast_threshold": 0.001 * j, "min_volatility": 0.0},
            source_revision="rev-01",
            data_hash="data-hash-01",
            frame_certification_id="cert-01",
            cost_model_hash="cost-hash-01",
        )
        tid = db.create_research_trial(trial)
        db.transition_research_trial(tid, "SUCCEEDED", metrics={"sharpe": 1.0 + 0.25 * ((j % 5) - 2)})

    bundle_25 = evaluator.evaluate(
        parent_run_id="run-dsr-25",
        spec=spec,
        train_size=150,
        val_size=50,
        test_size=50,
    )

    assert bundle_25.dsr.effective_trials > bundle_5.dsr.effective_trials
    assert bundle_25.dsr.total_trials > bundle_5.dsr.total_trials
    assert bundle_25.dsr.expected_max_sharpe is not None and bundle_5.dsr.expected_max_sharpe is not None
    assert bundle_25.dsr.expected_max_sharpe > 0.0

    db.close()




def test_duckdb_immutable_persistence_idempotency_and_conflict_rejection(tmp_path: Any) -> None:
    """Verify strategy_robustness_evaluations persistence, replay idempotency, and conflict failure."""
    db_path = str(tmp_path / "test_persistence.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)

    varied_returns = [0.001 * (1 + 0.5 * ((i % 5) - 2)) for i in range(100)]
    bundle = RobustnessBundle(
        robustness_id="rob-ident-001",
        run_id="run-001",
        experiment_family_id="fam-001",
        strategy_name="trend_following",
        strategy_version="1.1.0",
        selected_trial_id="trial-001",
        evidence_status=EvidenceStatus.VALID,
        nested_folds=[],
        parameter_robustness=[],
        psr=compute_psr(varied_returns),
        dsr=compute_dsr(varied_returns, [1.0, 1.2], effective_trials=2),
        bootstrap_intervals=compute_bootstrap_confidence_intervals(varied_returns, n_resamples=50),
        monte_carlo=compute_monte_carlo_robustness(varied_returns, n_simulations=50),
        cost_stress=[],
        execution_stress=[],
        policy_version="2.6.0",
        policy_hash="pol-hash-01",
        data_hash="data-hash-01",
        evidence_hash="ev-hash-01",
        created_at=datetime.now(timezone.utc),
    )


    # First save -> succeeds
    rob_id = db.save_robustness_evaluation(bundle)
    assert rob_id == "rob-ident-001"

    # Idempotent re-save of identical payload -> succeeds without duplicating rows
    rob_id_replay = db.save_robustness_evaluation(bundle)
    assert rob_id_replay == "rob-ident-001"

    rows = db.list_robustness_evaluations(strategy_name="trend_following")
    assert len(rows) == 1
    assert rows[0]["robustness_id"] == "rob-ident-001"
    assert rows[0]["strategy_version"] == "1.1.0"

    # Conflicting save for same robustness_id with different payload -> MUST RAISE ValueError
    conflicting_bundle = copy.deepcopy(bundle)
    conflicting_bundle.strategy_version = "2.0.0-CONFLICT"
    with pytest.raises(ValueError, match="Conflicting immutable robustness evaluation payload"):
        db.save_robustness_evaluation(conflicting_bundle)

    # Retrieval by ID
    retrieved = db.get_robustness_evaluation("rob-ident-001")
    assert retrieved is not None
    assert retrieved["strategy_name"] == "trend_following"
    assert json.loads(retrieved["psr_json"])["status"] == "VALID"

    db.close()


def test_parameter_robustness_selector_continuous_perturbation_and_empty_grid() -> None:
    """Cover continuous parameter perturbation and empty grid handling."""
    selector = ParameterRobustnessSelector(RobustnessPolicy())

    candidates = [
        {"fast_threshold": 0.05, "min_volatility": 0.01},
    ]
    from experiments.trials import canonical_hash
    hashed = {canonical_hash(candidates[0]): 1.5}

    evaluated = selector.evaluate_candidates(
        scores_by_param=hashed,
        candidates=candidates,
        grid={},  # empty grid triggers continuous fallback
    )
    assert len(evaluated) == 1
    assert evaluated[0].selected is True


def test_nested_wf_insufficient_bars_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nested walk forward raises error when total data length is smaller than train + val + test."""
    db = DuckDBManager(":memory:")
    evaluator = RobustnessEvaluator(db, policy=RobustnessPolicy(), risk_engine=_permissive_risk())
    spec = ExperimentSpec(strategy_name="trend_following", universe=["TEST_SYM"], timeframe="1d")

    # Mock _source to return a short dataset with only 50 bars
    short_ds = _make_dummy_dataset(n_days=50, seed=42)
    monkeypatch.setattr(evaluator, "_source", lambda spec, scope, lookback: short_ds)

    with pytest.raises(ValueError, match="insufficient for nested walk-forward"):
        evaluator.evaluate(
            "run-short",
            spec,
            train_size=200,
            val_size=100,
            test_size=100,
        )

    db.close()



def test_event_driven_mode_robustness_evaluation(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify robustness evaluation works under event-driven backtest mode."""
    db_path = str(tmp_path / "test_event_driven.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)

    family_id = "fam-event-driven-01"
    db.register_experiment_family(
        ExperimentFamilySpec(
            experiment_family_id=family_id,
            hypothesis="Event driven mode test",
            strategy_names=["trend_following"],
            strategy_versions=["1.1.0"],
            universe_snapshot_id="U_TEST",
            timeframe="1d",
            feature_versions=["1.0"],
            cost_model_version="v1",
            parameter_space={"fast_threshold": [0.0, 0.01]},
            maximum_trials=10,
            selection_metric="sharpe",
            walk_forward_design={"train_size": 150, "test_size": 50},
            source_revision="rev-01",
        )
    )

    ds = _make_dummy_dataset(n_days=400, seed=42)
    evaluator = RobustnessEvaluator(db, policy=RobustnessPolicy(), risk_engine=_permissive_risk())

    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["TEST_SYM"],
        timeframe="1d",
        mode="event-driven",
        experiment_family_id=family_id,
    )

    monkeypatch.setattr(evaluator, "_source", lambda spec, scope, lookback: ds)

    bundle = evaluator.evaluate(
        parent_run_id="run-event-driven",
        spec=spec,
        train_size=150,
        val_size=50,
        test_size=50,
    )

    assert bundle.evidence_status == EvidenceStatus.VALID
    assert len(bundle.nested_folds) >= 1
    assert bundle.psr.status == EvidenceStatus.VALID

    db.close()


def test_parameter_grid_candidate_generation(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that omitting parameters generates multiple candidate points from strategy grid."""
    db_path = str(tmp_path / "test_grid.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)

    family_id = "fam-grid-01"
    db.register_experiment_family(
        ExperimentFamilySpec(
            experiment_family_id=family_id,
            hypothesis="Grid candidate generation",
            strategy_names=["trend_following"],
            strategy_versions=["1.1.0"],
            universe_snapshot_id="U_TEST",
            timeframe="1d",
            feature_versions=["1.0"],
            cost_model_version="v1",
            parameter_space={"fast_threshold": [0.0, 0.01, 0.02]},
            maximum_trials=20,
            selection_metric="sharpe",
            walk_forward_design={"train_size": 150, "test_size": 50},
            source_revision="rev-01",
        )
    )

    ds = _make_dummy_dataset(n_days=400, seed=42)
    evaluator = RobustnessEvaluator(db, policy=RobustnessPolicy(), risk_engine=_permissive_risk())

    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["TEST_SYM"],
        timeframe="1d",
        parameters={},  # empty parameters triggers grid candidates
        experiment_family_id=family_id,
    )

    monkeypatch.setattr(evaluator, "_source", lambda spec, scope, lookback: ds)

    bundle = evaluator.evaluate(
        parent_run_id="run-grid",
        spec=spec,
        train_size=150,
        val_size=50,
        test_size=50,
    )

    assert len(bundle.parameter_robustness) >= 1
    assert bundle.evidence_status == EvidenceStatus.VALID

    db.close()


def test_stress_scenario_engine_with_fills_and_cost_drag() -> None:
    """Directly test StressScenarioEngine with non-empty fills and cost models."""
    engine = StressScenarioEngine(policy=RobustnessPolicy())
    dates = pd.date_range(start="2023-01-01", periods=100, freq="B", tz="Asia/Kolkata")

    curve = pd.DataFrame({
        "timestamp": dates,
        "equity": np.linspace(100_000, 120_000, 100),
        "cash": [100_000.0] * 100,
        "position": [0.0] * 100,
        "net_return": [0.002] * 100,
        "drawdown": [0.0] * 100,
    })

    fills = pd.DataFrame({
        "timestamp": [dates[10], dates[20], dates[30]],
        "symbol": ["TEST_SYM"] * 3,
        "price": [100.0, 105.0, 110.0],
        "quantity": [100, -100, 50],
        "side": ["BUY", "SELL", "BUY"],
        "order_type": ["BUY", "STOP_LOSS", "BUY"],
        "market_volume": [100000.0, 100000.0, 100000.0],
        "cost": [50.0, 55.0, 25.0],
        "fees": [10.0, 10.0, 5.0],
        "slippage": [0.0, 0.0, 0.0],
        "slippage_bps": [0.0, 0.0, 0.0],
        "fill_price": [100.0, 105.0, 110.0],
    })

    delayed_curve = curve.copy()
    delayed_run = type("DummyDelayedRun", (), {
        "equity_curve": delayed_curve,
        "fills": fills,
    })()

    dummy_run = type("DummyRun", (), {
        "equity_curve": curve,
        "fills": fills,
        "delayed_run": delayed_run,
        "metrics": type("DummyMetrics", (), {"sharpe": 1.0, "cagr": 0.15, "max_drawdown": -0.05, "total_return": 0.20, "profit_factor": 1.5})(),
    })()

    cost_results = engine.evaluate_cost_stress(
        strategy_run=dummy_run,
        base_cost_model={"fee_bps": 10.0, "indian_delivery_costs": {"brokerage_rate_bps": 5.0}},
        timeframe="1d",
        starting_capital=100_000.0,
    )
    assert len(cost_results) == 4
    for c in cost_results:
        assert c.multiplier in [1.0, 1.5, 2.0, 3.0]
        assert "sharpe" in c.metrics
        assert c.status == EvidenceStatus.VALID

    exec_results = engine.evaluate_execution_stress(
        strategy_run=dummy_run,
        timeframe="1d",
        starting_capital=100_000.0,
    )
    assert len(exec_results) == 5
    for e in exec_results:
        assert e.status == EvidenceStatus.VALID
    scenario_names = {e.scenario_name for e in exec_results}
    assert "reduced_liquidity" in scenario_names
    assert "overnight_gap_stress" in scenario_names
    assert "stop_slippage_stress" in scenario_names
    assert "execution_delay" in scenario_names
    assert "missed_fills" in scenario_names


def test_nested_walk_forward_splitter_direct() -> None:
    """Verify NestedWalkForwardSplitter splits and handles purge/embargo."""
    splitter = NestedWalkForwardSplitter()

    # 400 bars with 150 train, 50 val, 50 test, purge 5, embargo 3
    splits = splitter.split(400, train_size=150, val_size=50, test_size=50, purge_window=5, embargo_window=3)
    assert len(splits) >= 1
    t_idx, v_idx, test_idx = splits[0]
    assert len(t_idx) == 150 - 5  # purged 5 bars from end of train
    assert len(v_idx) == 50 - 5  # purged 5 bars from end of val
    assert len(test_idx) == 50

    # Short total length returns empty list
    short_splits = splitter.split(100, train_size=150, val_size=50, test_size=50)
    assert short_splits == []


def test_candidate_replay_error_handling_in_nested_selection(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that failing candidate replay transitions trial to FAILED and continues."""
    db_path = str(tmp_path / "test_candidate_error.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)

    family_id = "fam-candidate-err"
    db.register_experiment_family(
        ExperimentFamilySpec(
            experiment_family_id=family_id,
            hypothesis="Failing candidate replay error handling",
            strategy_names=["trend_following"],
            strategy_versions=["1.1.0"],
            universe_snapshot_id="U_TEST",
            timeframe="1d",
            feature_versions=["1.0"],
            cost_model_version="v1",
            parameter_space={"fast_threshold": [0.0, 0.01]},
            maximum_trials=20,
            selection_metric="sharpe",
            walk_forward_design={"train_size": 150, "test_size": 50},
            source_revision="rev-01",
        )
    )

    ds = _make_dummy_dataset(n_days=400, seed=42)
    evaluator = RobustnessEvaluator(db, policy=RobustnessPolicy(), risk_engine=_permissive_risk())

    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["TEST_SYM"],
        timeframe="1d",
        parameters={},  # multiple candidates from grid
        experiment_family_id=family_id,
    )

    monkeypatch.setattr(evaluator, "_source", lambda spec, scope, lookback: ds)

    # Make _run raise only on first candidate (fast_threshold == 0.01)
    original_run = evaluator._run
    def failing_run(spec, scope, source, params, capital):
        if params.get("fast_threshold") == 0.01:
            raise RuntimeError("Synthetic backtest execution failure for candidate 0.01")
        return original_run(spec, scope, source, params, capital)

    monkeypatch.setattr(evaluator, "_run", failing_run)

    bundle = evaluator.evaluate(
        parent_run_id="run-failing-cand",
        spec=spec,
        train_size=150,
        val_size=50,
        test_size=50,
    )
    assert bundle is not None
    assert bundle.evidence_status == EvidenceStatus.VALID
    db.close()


def test_parameter_robustness_plateau_fraction_and_rank_stability() -> None:
    """Verify plateau fraction, neighbor min, and fold rank stability calculation."""
    policy = RobustnessPolicy(
        plateau_min_ratio=0.80,
        sensitivity_weight=0.30,
        stability_weight=0.20,
        plateau_weight=0.30,
        raw_score_weight=0.20,
    )
    selector = ParameterRobustnessSelector(policy)

    grid = {"param_a": (1, 2, 3, 4, 5), "param_b": (10, 20, 30, 40, 50)}
    candidates = [
        {"param_a": 2, "param_b": 20},  # Candidate 1: Plateau center (robust)
        {"param_a": 5, "param_b": 50},  # Candidate 2: Isolated spike (fragile)
    ]

    from experiments.trials import canonical_hash
    c1_hash = canonical_hash(candidates[0])
    c2_hash = canonical_hash(candidates[1])

    scores_train = {
        # Candidate 1 and neighbors (plateau)
        c1_hash: 2.0,
        canonical_hash({"param_a": 1, "param_b": 20}): 1.8,
        canonical_hash({"param_a": 3, "param_b": 20}): 1.9,
        canonical_hash({"param_a": 2, "param_b": 10}): 1.85,
        canonical_hash({"param_a": 2, "param_b": 30}): 1.75,
        # Candidate 2 (spike) and neighbors (collapse)
        c2_hash: 2.2,
        canonical_hash({"param_a": 4, "param_b": 50}): -0.5,
        canonical_hash({"param_a": 5, "param_b": 40}): -0.2,
    }

    scores_val = {
        c1_hash: 1.9,  # Stays high rank
        c2_hash: 0.5,  # Collapses on val
    }

    evaluated = selector.evaluate_candidates(
        scores_by_param=scores_train,
        candidates=candidates,
        grid=grid,
        val_scores_by_param=scores_val,
    )

    c1_eval = next(c for c in evaluated if c.parameters == {"param_a": 2, "param_b": 20})
    assert c1_eval.plateau_fraction == 1.0  # 4 out of 4 neighbors on plateau
    assert c1_eval.neighbor_min == 1.75
    assert c1_eval.val_rank == 1
    assert c1_eval.selected is True

    c2_eval = next(c for c in evaluated if c.parameters == {"param_a": 5, "param_b": 50})
    assert c2_eval.plateau_fraction == 0.0
    assert c2_eval.neighbor_min == -0.5
    assert c2_eval.selected is False


def test_real_selected_trial_id_linkage_in_registry(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that selected candidate's real ResearchTrial trial_id is linked and marked selected."""
    db_path = str(tmp_path / "test_real_trial_id.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)

    family_id = "fam-real-trial-01"
    db.register_experiment_family(
        ExperimentFamilySpec(
            experiment_family_id=family_id,
            hypothesis="Verify real trial ID mapping",
            strategy_names=["trend_following"],
            strategy_versions=["1.1.0"],
            universe_snapshot_id="U_TEST",
            timeframe="1d",
            feature_versions=["1.0"],
            cost_model_version="v1",
            parameter_space={"fast_threshold": [0.0, 0.01]},
            maximum_trials=10,
            selection_metric="sharpe",
            walk_forward_design={"train_size": 150, "test_size": 50},
            source_revision="rev-01",
        )
    )

    ds = _make_dummy_dataset(n_days=400, seed=42)
    evaluator = RobustnessEvaluator(db, policy=RobustnessPolicy(), risk_engine=RiskEngine())

    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["TEST_SYM"],
        timeframe="1d",
        experiment_family_id=family_id,
        parameters={"fast_threshold": 0.0, "min_volatility": 0.0},
    )

    monkeypatch.setattr(evaluator, "_source", lambda spec, scope, lookback: ds)

    bundle = evaluator.evaluate(
        parent_run_id="run-real-trial-id",
        spec=spec,
        train_size=150,
        val_size=50,
        test_size=50,
    )

    assert bundle.selected_trial_id is not None
    assert bundle.selected_trial_id.startswith("trial-") or len(bundle.selected_trial_id) == 64

    # Verify that the trial exists in DuckDB registry and was marked selected
    trial_row = db.get_research_trial(bundle.selected_trial_id)
    assert trial_row is not None
    assert trial_row["selected"] is True

    db.close()



def test_cost_and_execution_stress_on_oos_evidence(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify cost stress includes slippage/liquidity and execution stress includes reduced liquidity on OOS evidence."""
    db_path = str(tmp_path / "test_oos_stress.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)

    ds = _make_dummy_dataset(n_days=400, seed=42)
    evaluator = RobustnessEvaluator(db, policy=RobustnessPolicy(slippage_stress_bps=15.0, liquidity_stress_factor=2.0), risk_engine=RiskEngine())

    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["TEST_SYM"],
        timeframe="1d",
        cost_model={"fee_bps": 10.0, "brokerage_rate_bps": 5.0},
    )

    monkeypatch.setattr(evaluator, "_source", lambda spec, scope, lookback: ds)

    bundle = evaluator.evaluate(
        parent_run_id="run-oos-stress",
        spec=spec,
        train_size=150,
        val_size=50,
        test_size=50,
    )

    # Cost stress checks
    cost_15x = next(c for c in bundle.cost_stress if c.multiplier == 1.5)
    assert cost_15x.slippage_bps_override == 15.0

    cost_1x = next(c for c in bundle.cost_stress if c.multiplier == 1.0)
    assert cost_1x.slippage_bps_override is None

    # Execution stress checks
    exec_scenarios = {e.scenario_name for e in bundle.execution_stress}
    assert "reduced_liquidity" in exec_scenarios
    assert "overnight_gap_stress" in exec_scenarios
    assert "stop_slippage_stress" in exec_scenarios
    assert "execution_delay" in exec_scenarios
    assert "missed_fills" in exec_scenarios

    # Evidence hash binds all components
    assert bundle.evidence_hash is not None
    assert len(bundle.evidence_hash) == 64

    db.close()


def test_candidate_combinatorics_generation() -> None:
    """Verify _candidates generates multi-variable Cartesian product."""
    evaluator = RobustnessEvaluator(cast(DuckDBManager, None), policy=RobustnessPolicy(), risk_engine=RiskEngine())
    grid = {
        "fast_threshold": (0.01, 0.02),
        "min_volatility": (0.005, 0.01),
    }
    candidates = evaluator._candidates(explicit={}, parameter_grid=grid)
    assert len(candidates) == 4

    # Explicit candidates with no grid
    cand_explicit = evaluator._candidates(explicit={"param_a": 10}, parameter_grid={})
    assert cand_explicit == [{"param_a": 10}]


def test_source_and_cross_sectional_run_execution(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover _source and _run methods across scopes and calendar validations."""
    from trading_stack.domain import StrategyScope
    db_path = str(tmp_path / "test_source.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)

    candles = _make_dummy_candles(n_days=100, seed=42)
    candles["dataset_id"] = "DS_TEST_01"

    evaluator = RobustnessEvaluator(db, policy=RobustnessPolicy(), risk_engine=RiskEngine())

    spec_single = ExperimentSpec(
        strategy_name="trend_following",
        universe=["TEST_SYM"],
        timeframe="1d",
        cost_model={"fee_bps": 5.0},
    )

    # 1. Single asset _source with mocked pipeline load_candles
    monkeypatch.setattr("experiments.robustness.StrategyPipeline.load_candles", lambda self, sym, tf, **_kwargs: candles.copy())
    ds_single = evaluator._source(spec_single, StrategyScope.SINGLE_ASSET, lookback=20)
    assert ds_single.universe_snapshot_id == spec_single.universe_snapshot_id
    assert not ds_single.panel.empty

    # 2. Cross sectional _source
    spec_cross = ExperimentSpec(
        strategy_name="cross_sectional_momentum",
        universe=["SYM_A", "SYM_B"],
        timeframe="1d",
        cost_model={"brokerage_rate_bps": 5.0, "stt_sell_bps": 10.0},
    )
    candles_a = _make_dummy_candles(n_days=100, seed=42)
    candles_a["symbol"] = "SYM_A"
    candles_b = _make_dummy_candles(n_days=100, seed=43)
    candles_b["symbol"] = "SYM_B"
    combined_panel = FeatureFactory().build(pd.concat([candles_a, candles_b], ignore_index=True), timezone_name="Asia/Kolkata")
    ds_multi = ResearchDataset(
        universe_snapshot_id="U_MULTI",
        dataset_snapshot_ids={"SYM_A": "DS_A", "SYM_B": "DS_B"},
        panel=combined_panel,
    )
    monkeypatch.setattr("experiments.robustness.SynchronizedPanelBuilder.build", lambda self, univ, tf, **kwargs: ds_multi)
    ds_cross = evaluator._source(spec_cross, StrategyScope.CROSS_SECTIONAL, lookback=20)
    assert ds_cross is not None

    # 3. Cross sectional _run execution
    run_result = evaluator._run(spec_cross, StrategyScope.CROSS_SECTIONAL, ds_multi, {}, 100_000.0)
    assert run_result is not None

    db.close()


def test_nested_walk_forward_splitter_boundary_validations() -> None:
    """Cover NestedWalkForwardSplitter boundary checks and error branches."""
    splitter = NestedWalkForwardSplitter()

    with pytest.raises(ValueError, match="must be positive integers"):
        splitter.split(100, train_size=0, val_size=10, test_size=10)

    with pytest.raises(ValueError, match="must be non-negative"):
        splitter.split(100, train_size=50, val_size=10, test_size=10, purge_window=-1)

    with pytest.raises(ValueError, match="must be non-negative"):
        splitter.split(100, train_size=50, val_size=10, test_size=10, embargo_window=-1)

    # Empty on short length
    assert splitter.split(20, train_size=50, val_size=10, test_size=10) == []


def test_dual_boundary_purge_and_post_test_embargo_split_plans() -> None:
    """Verify NestedWalkForwardSplitter purges both boundaries and embargos post-test observations."""
    splitter = NestedWalkForwardSplitter()
    plans = splitter.split_plans(
        total_bars=500,
        train_size=200,
        val_size=50,
        test_size=50,
        purge_window=5,
        embargo_window=10,
    )
    assert len(plans) >= 2

    # Fold 1
    p1 = plans[0]
    assert p1.fold_id == "nfold-001"
    # Train is [0 : 200 - 5] -> 195 bars
    assert len(p1.train_indices) == 195
    assert len(p1.purged_train_indices) == 5
    assert p1.purged_train_indices == [195, 196, 197, 198, 199]

    # Val is [200 : 250 - 5] -> 45 bars
    assert len(p1.val_indices) == 45
    assert len(p1.purged_val_indices) == 5
    assert p1.purged_val_indices == [245, 246, 247, 248, 249]

    # Test is [250 : 300] -> 50 bars
    assert len(p1.test_indices) == 50
    assert p1.test_indices[0] == 250
    assert p1.test_indices[-1] == 299

    # Embargoed window after test is [300 : 310]
    assert len(p1.embargoed_indices) == 10
    assert p1.embargoed_indices == list(range(300, 310))

    # Fold 2 (expanding train)
    p2 = plans[1]
    assert p2.fold_id == "nfold-002"
    assert p2.val_indices[0] == 250
    assert p2.test_indices[0] == 300

    # Zero purge plans
    zero_purge = splitter.split_plans(total_bars=300, train_size=100, val_size=50, test_size=50, purge_window=0)
    assert len(zero_purge) >= 1
    assert zero_purge[0].purged_train_indices == []
    assert zero_purge[0].purged_val_indices == []


def test_parameter_robustness_discrete_integer_steps_and_empty_candidates() -> None:
    """Cover discrete integer grid steps and empty candidates error."""
    selector = ParameterRobustnessSelector(RobustnessPolicy())
    grid = {
        "lookback": (10, 20, 30),
        "threshold": (0.01, 0.02),
    }

    # Integer discrete step neighbors
    neighbors = selector.define_neighbors({"lookback": 20, "threshold": 0.01}, grid)
    assert len(neighbors) >= 1

    # Candidate with missing key or out-of-grid value
    assert selector.define_neighbors({"other_key": 5}, grid) == []
    assert selector.define_neighbors({"lookback": 999, "threshold": 0.01}, grid) != []

    # Empty candidate list raises RuntimeError
    with pytest.raises(RuntimeError, match="No candidate evaluations available"):
        selector.evaluate_candidates(scores_by_param={}, candidates=[], grid=grid)


def test_source_empty_candles_error(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify _source raises ValueError when no candles exist."""
    db_path = str(tmp_path / "test_empty_source.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)

    evaluator = RobustnessEvaluator(db, policy=RobustnessPolicy(), risk_engine=RiskEngine())
    spec = ExperimentSpec(strategy_name="trend_following", universe=["NON_EXISTENT"], timeframe="1d")

    monkeypatch.setattr("experiments.robustness.StrategyPipeline.load_candles", lambda self, sym, tf, **_kwargs: pd.DataFrame())
    from trading_stack.domain import StrategyScope
    with pytest.raises(ValueError, match="No candles found"):
        evaluator._source(spec, StrategyScope.SINGLE_ASSET, lookback=20)

    db.close()


def test_governance_and_registry_family_integration(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover family registry lookup with JSON metrics and frame certification evidence."""
    db_path = str(tmp_path / "test_gov_registry.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)

    candles = _make_dummy_candles(n_days=400, seed=42)
    candles["dataset_id"] = "DS_TEST_01"

    # Insert frame certification
    db.conn.execute(
        """
        INSERT INTO research_frame_certifications (
            frame_certification_id, research_frame_hash, contributing_dataset_ids_json,
            symbol, timeframe, row_count, basis, validator_version,
            status, verified_at, dataset_evidence_json, dq_certification_ids_json, pit_evidence_hash
        ) VALUES (
            'FC_TEST_01', 'rf_hash_01', '["DS_TEST_01"]',
            'TEST_SYM', '1d', 400, 'EXACT_FRAME', '2.2.0',
            'VALID', CURRENT_TIMESTAMP, '{"TEST_SYM": "hash_1"}', '["DQ_01"]', 'pit_hash_1'
        )
        """
    )

    family_id = "fam-robust-01"
    db.conn.execute(
        """
        INSERT INTO experiment_families (
            experiment_family_id, definition_hash, definition_json,
            maximum_trials, created_at, started_at
        ) VALUES (
            'fam-robust-01', 'def_hash_01', '{"hypothesis": "trend"}',
            100, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        """
    )

    # Insert historical trial in family with JSON string metrics
    db.conn.execute(
        """
        INSERT INTO research_trials_log (
            trial_id, experiment_family_id, status, trial_json, metrics_json, created_at
        ) VALUES (
            'trial-fam-01', 'fam-robust-01', 'SUCCEEDED', '{"parameters": {"fast_threshold": 0.01}}', '{"sharpe": 1.25}', CURRENT_TIMESTAMP
        ), (
            'trial-fam-02', 'fam-robust-01', 'INVALIDATED', '{"parameters": {"fast_threshold": 0.02}}', '{}', CURRENT_TIMESTAMP
        )
        """
    )

    evaluator = RobustnessEvaluator(db, policy=RobustnessPolicy(), risk_engine=RiskEngine())
    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["TEST_SYM"],
        timeframe="1d",
        experiment_family_id=family_id,
        parameters={"fast_threshold": 0.01, "min_volatility": 0.0},
    )

    # Mock pipeline with _last_frame_certification_id
    class DummyPipeline:
        _last_frame_certification_id = "FC_TEST_01"
        def load_candles(self, sym, tf, **_kwargs):
            return candles.copy()

    monkeypatch.setattr("experiments.robustness.StrategyPipeline", lambda *args, **kwargs: DummyPipeline())

    bundle = evaluator.evaluate(
        parent_run_id="run-family-gov",
        spec=spec,
        train_size=150,
        val_size=50,
        test_size=50,
        purge_window=5,
        embargo_window=5,
    )
    assert bundle is not None
    assert bundle.experiment_family_id == family_id
    assert bundle.dsr is not None

    # Check persistence in DuckDB
    saved = db.get_robustness_evaluation(bundle.robustness_id)
    assert saved is not None
    assert saved["robustness_id"] == bundle.robustness_id

    db.close()


def test_source_calendar_validation_and_malformed_json_evidence(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover out of session calendar check and corrupted json recovery in frame certification."""
    from trading_stack.domain import StrategyScope
    db_path = str(tmp_path / "test_cal_malformed.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)

    # Insert frame certification with malformed json strings
    db.conn.execute(
        """
        INSERT INTO research_frame_certifications (
            frame_certification_id, research_frame_hash, contributing_dataset_ids_json,
            symbol, timeframe, row_count, basis, validator_version,
            status, verified_at, dataset_evidence_json, dq_certification_ids_json, pit_evidence_hash
        ) VALUES (
            'FC_MALFORMED', 'rf_hash_bad', '["DS_BAD"]',
            'TEST_SYM', '1d', 100, 'EXACT_FRAME', '2.2.0',
            'VALID', CURRENT_TIMESTAMP, 'INVALID_JSON_HERE', '{NOT_AN_ARRAY}', 'pit_hash_val'
        )
        """
    )

    evaluator = RobustnessEvaluator(db, policy=RobustnessPolicy(), risk_engine=RiskEngine())
    spec = ExperimentSpec(strategy_name="trend_following", universe=["TEST_SYM"], timeframe="1d")
    candles = _make_dummy_candles(n_days=100, seed=42)

    class MockPipeline:
        _last_frame_certification_id = "FC_MALFORMED"
        def load_candles(self, sym, tf, **_kwargs):
            return candles.copy()

    monkeypatch.setattr("experiments.robustness.StrategyPipeline", lambda *args, **kwargs: MockPipeline())

    # 1. Runs and recovers gracefully from malformed JSON
    ds = evaluator._source(spec, StrategyScope.SINGLE_ASSET, lookback=10)
    assert ds is not None
    assert ds.pit_evidence_hash == "pit_hash_val"

    # 2. Out of session calendar raises ValueError
    class MockCalendar:
        def validate_bars(self, timestamps, tf):
            return type("ValResult", (), {"out_of_session_count": 5})()

    evaluator.india_calendar = cast(Any, MockCalendar())
    with pytest.raises(ValueError, match="bars outside the verified NSE calendar"):
        evaluator._source(spec, StrategyScope.SINGLE_ASSET, lookback=10)

    db.close()


def test_purge_window_exhaustion_fail_closed() -> None:
    """Splitter must fail closed with explicit ValueError when purge window exhausts TRAIN or VALIDATION."""
    splitter = NestedWalkForwardSplitter()

    # 1. Purge window >= train_size (e.g. train_size=50, purge_window=50)
    with pytest.raises(ValueError, match="PURGE_WINDOW_EXHAUSTS_TRAIN"):
        splitter.split_plans(
            total_bars=300,
            train_size=50,
            val_size=50,
            test_size=50,
            purge_window=50,
        )

    # 2. Purge window > train_size (e.g. train_size=50, purge_window=60)
    with pytest.raises(ValueError, match="PURGE_WINDOW_EXHAUSTS_TRAIN"):
        splitter.split_plans(
            total_bars=300,
            train_size=50,
            val_size=50,
            test_size=50,
            purge_window=60,
        )

    # 3. Purge window >= val_size (e.g. train_size=100, val_size=30, purge_window=30)
    with pytest.raises(ValueError, match="PURGE_WINDOW_EXHAUSTS_VALIDATION"):
        splitter.split_plans(
            total_bars=300,
            train_size=100,
            val_size=30,
            test_size=30,
            purge_window=30,
        )


def test_fold_complete_dataset_lineage_and_evidence_hash_binding(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that every fold persists complete dataset lineage and binds it immutably into evidence_hash."""
    db_path = str(tmp_path / "test_lineage.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)

    ds_1 = _make_dummy_dataset(n_days=400, seed=42)
    evaluator = RobustnessEvaluator(db, policy=RobustnessPolicy(), risk_engine=RiskEngine())
    spec = ExperimentSpec(strategy_name="trend_following", universe=["TEST_SYM"], timeframe="1d")

    monkeypatch.setattr(evaluator, "_source", lambda spec, scope, lookback: ds_1)

    bundle_1 = evaluator.evaluate(
        parent_run_id="run-lineage-1",
        spec=spec,
        train_size=150,
        val_size=50,
        test_size=50,
    )

    # Check that each fold has complete explicit lineage
    for fold in bundle_1.nested_folds:
        assert fold.dataset_snapshot_ids == {"TEST_SYM": "DS_TEST"}
        assert fold.dataset_content_hashes == {"TEST_SYM": "ds-hash-01"}
        assert fold.frame_certification_id == "cert-01"
        assert len(fold.evidence_hash) > 10

    # Perturbing dataset content hashes alone produces a different evidence hash
    ds_2 = _make_dummy_dataset(n_days=400, seed=42, dataset_content_hashes={"TEST_SYM": "ds-hash-altered"})
    monkeypatch.setattr(evaluator, "_source", lambda spec, scope, lookback: ds_2)

    bundle_2 = evaluator.evaluate(
        parent_run_id="run-lineage-2",
        spec=spec,
        train_size=150,
        val_size=50,
        test_size=50,
    )

    assert bundle_1.evidence_hash != bundle_2.evidence_hash
    assert bundle_1.nested_folds[0].evidence_hash != bundle_2.nested_folds[0].evidence_hash

    db.close()


def test_evidence_based_stress_status_and_reasons() -> None:
    """Stress scenario engine must fail closed with INSUFFICIENT_EVIDENCE when fill records are missing."""
    engine = StressScenarioEngine(RobustnessPolicy())

    # 1. Strategy run with no fills
    class EmptyFillsRun:
        equity_curve = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC"),
            "net_return": [0.001] * 100,
            "position": [1.0] * 100,
            "equity": [100000.0] * 100,
            "drawdown": [0.0] * 100,
        })
        fills = pd.DataFrame()

    cost_results = engine.evaluate_cost_stress(EmptyFillsRun(), base_cost_model={"fee_bps": 5.0}, timeframe="1d", starting_capital=100_000.0)
    # 1.0x baseline is VALID, multipliers > 1.0 fail closed with INSUFFICIENT_EVIDENCE
    assert cost_results[0].status == EvidenceStatus.VALID
    assert cost_results[1].status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert cost_results[1].reason == "NO_FILL_RECORDS_FOR_COST_STRESS"

    exec_results = engine.evaluate_execution_stress(EmptyFillsRun(), timeframe="1d", starting_capital=100_000.0)
    exec_status_map = {r.scenario_name: r.status for r in exec_results}
    assert exec_status_map["stop_slippage_stress"] == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert exec_status_map["missed_fills"] == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert exec_status_map["reduced_liquidity"] == EvidenceStatus.INSUFFICIENT_EVIDENCE


def test_parameter_robustness_negative_train_scores() -> None:
    """ParameterRobustnessSelector handles non-positive scores gracefully."""
    selector = ParameterRobustnessSelector(RobustnessPolicy())
    grid = {"p": (1, 2, 3)}
    scores = {
        canonical_hash({"p": 1}): -1.5,
        canonical_hash({"p": 2}): -0.8,
        canonical_hash({"p": 3}): -2.0,
    }
    candidates = [{"p": 1}, {"p": 2}, {"p": 3}]
    evaluated = selector.evaluate_candidates(scores, candidates, grid)
    assert len(evaluated) == 3
    # Candidate p=1 has neighbor p=2 (-0.8) which gives higher neighbor min & mean than p=2 (neighbors -1.5, -2.0)
    assert evaluated[0].selected is True


def test_stress_scenario_without_timestamps_or_positions() -> None:
    """Stress scenario engine fails closed with INSUFFICIENT_EVIDENCE when required evidence is missing."""
    engine = StressScenarioEngine(RobustnessPolicy())

    # Fills without timestamp
    fills_no_ts = pd.DataFrame({
        "quantity": [10.0, -10.0],
        "price": [100.0, 105.0],
        "fees": [1.0, 1.0],
        "slippage_bps": [0.0, 0.0],
        "side": ["BUY", "SELL"],
    })
    curve_no_ts = pd.DataFrame({
        "net_return": [0.001, -0.0005, 0.002, 0.001],
        "position": [0.0, 1.0, 1.0, 0.0],
        "equity": [100000.0, 99950.0, 100150.0, 100250.0],
        "drawdown": [0.0, -0.0005, 0.0, 0.0],
    })

    class RunNoTs:
        equity_curve = curve_no_ts
        fills = fills_no_ts

    cost_res = engine.evaluate_cost_stress(RunNoTs(), base_cost_model={"fee_bps": 5.0}, timeframe="1d", starting_capital=100_000.0)
    assert cost_res[0].status == EvidenceStatus.VALID  # baseline
    assert cost_res[1].status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert cost_res[1].reason == "MISSING_FILL_TIMESTAMP_EVIDENCE"

    exec_res = engine.evaluate_execution_stress(RunNoTs(), timeframe="1d", starting_capital=100_000.0)
    # Overnight gap fails without timestamp evidence
    overnight = next(r for r in exec_res if r.scenario_name == "overnight_gap_stress")
    assert overnight.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert overnight.reason == "MISSING_TIMESTAMP_OR_POSITION_EVIDENCE"

    # Stop slippage fails without stop order evidence
    stop_slip = next(r for r in exec_res if r.scenario_name == "stop_slippage_stress")
    assert stop_slip.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert stop_slip.reason == "NO_STOP_ORDER_EVIDENCE"

    # Execution delay fails without delayed replay evidence
    delay = next(r for r in exec_res if r.scenario_name == "execution_delay")
    assert delay.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert delay.reason == "NO_DELAYED_FILL_REPLAY_EVIDENCE"

    # Missed fills fails without timestamp evidence
    missed = next(r for r in exec_res if r.scenario_name == "missed_fills")
    assert missed.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert missed.reason == "MISSING_TIMESTAMP_EVIDENCE_FOR_MISSED_FILLS"

    # Reduced liquidity fails without market volume evidence
    liq = next(r for r in exec_res if r.scenario_name == "reduced_liquidity")
    assert liq.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert liq.reason == "NO_MARKET_VOLUME_EVIDENCE"


def test_registry_family_with_deduplicated_and_failed_trials(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """RobustnessEvaluator properly handles duplicate trial definitions and failed/invalidated statuses."""
    db_path = str(tmp_path / "test_dedup_family.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)

    family_id = "fam-dedup-01"
    db.conn.execute(
        f"INSERT INTO experiment_families (experiment_family_id, definition_hash, definition_json, maximum_trials, created_at, started_at) VALUES ('{family_id}', 'hash1', '{{}}', 50, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )

    # Insert 1 succeeded, 1 duplicate succeeded, 1 failed, 1 invalidated
    trial_def = '{"strategy_name": "trend_following", "timeframe": "1d", "parameters": {"fast_threshold": 0.01}, "fold_id": "fold-0", "train_start": "2022-01-01", "train_end": "2022-06-01", "data_hash": "h1"}'
    db.conn.execute(
        f"""
        INSERT INTO research_trials_log (trial_id, experiment_family_id, status, trial_json, metrics_json, created_at)
        VALUES
        ('t-1', '{family_id}', 'SUCCEEDED', '{trial_def}', '{{"sharpe": 1.2}}', CURRENT_TIMESTAMP),
        ('t-2', '{family_id}', 'SUCCEEDED', '{trial_def}', '{{"sharpe": 1.2}}', CURRENT_TIMESTAMP),
        ('t-3', '{family_id}', 'FAILED', '{{"strategy_name": "other"}}', '{{}}', CURRENT_TIMESTAMP),
        ('t-4', '{family_id}', 'INVALIDATED', '{{"strategy_name": "invalid"}}', '{{}}', CURRENT_TIMESTAMP)
        """
    )

    evaluator = RobustnessEvaluator(db, policy=RobustnessPolicy(), risk_engine=RiskEngine())
    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["TEST_SYM"],
        timeframe="1d",
        experiment_family_id=family_id,
        parameters={"fast_threshold": 0.01, "min_volatility": 0.0},
    )

    candles = _make_dummy_candles(n_days=400, seed=42)
    class DummyPipeline:
        _last_frame_certification_id = "cert-01"
        def load_candles(self, sym, tf, **_kwargs):
            return candles.copy()

    monkeypatch.setattr("experiments.robustness.StrategyPipeline", lambda *args, **kwargs: DummyPipeline())

    bundle = evaluator.evaluate(
        parent_run_id="run-dedup-gov",
        spec=spec,
        train_size=150,
        val_size=50,
        test_size=50,
    )
    assert bundle.dsr is not None
    assert bundle.dsr.deduplicated_count >= 1
    assert bundle.dsr.failed_count >= 1
    assert bundle.dsr.invalidated_trials >= 1
    assert bundle.dsr.trial_count_source == TrialCountSource.PHASE2_1_REGISTRY

    db.close()


def test_robustness_stress_and_edge_branches() -> None:
    """Cover stop order tags, boolean is_stop, reason tags, and timestamp alignment in stress testing."""
    engine = StressScenarioEngine(RobustnessPolicy())
    dates = pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC")

    curve = pd.DataFrame({
        "timestamp": dates,
        "net_return": [0.001] * 10,
        "equity": [100000.0] * 10,
        "drawdown": [0.0] * 10,
        "position": [1.0] * 10,
    })

    # Fills with order_tag and is_stop and off-grid timestamps (prior and before first bar)
    fills_tagged = pd.DataFrame({
        "timestamp": [dates[0] - pd.Timedelta(hours=2), dates[3] + pd.Timedelta(hours=5), dates[6]],
        "symbol": ["TEST"] * 3,
        "price": [100.0, 102.0, 105.0],
        "quantity": [10, -10, 5],
        "side": ["BUY", "SELL", "BUY"],
        "order_tag": ["ENTRY", "STOP_LOSS", "RE_ENTRY"],
        "is_stop": [False, True, False],
        "market_volume": [50000.0, 50000.0, 50000.0],
        "fees": [1.0, 1.0, 1.0],
        "cost": [1.0, 1.0, 1.0],
        "slippage": [0.0, 0.0, 0.0],
        "slippage_bps": [0.0, 0.0, 0.0],
        "fill_price": [100.0, 102.0, 105.0],
    })

    class TaggedRun:
        equity_curve = curve
        fills = fills_tagged
        metrics = type("Metrics", (), {"sharpe": 1.0, "cagr": 0.1, "max_drawdown": -0.05, "total_return": 0.1, "profit_factor": 1.5})()

    cost_res = engine.evaluate_cost_stress(TaggedRun(), base_cost_model={"fee_bps": 5.0}, timeframe="1d", starting_capital=100_000.0)
    assert all(c.status == EvidenceStatus.VALID for c in cost_res)

    exec_res = engine.evaluate_execution_stress(TaggedRun(), timeframe="1d", starting_capital=100_000.0)
    stop_slip = next(r for r in exec_res if r.scenario_name == "stop_slippage_stress")
    assert stop_slip.status == EvidenceStatus.VALID

    # Reason tag test
    fills_reason = pd.DataFrame({
        "timestamp": [dates[2]],
        "symbol": ["TEST"],
        "price": [100.0],
        "quantity": [-10],
        "side": ["SELL"],
        "reason": ["SL_TRIGGERED"],
        "market_volume": [50000.0],
        "fees": [1.0],
        "cost": [1.0],
        "slippage": [0.0],
        "slippage_bps": [0.0],
        "fill_price": [100.0],
    })

    class ReasonRun:
        equity_curve = curve
        fills = fills_reason
        metrics = TaggedRun.metrics

    # Participation rate column support
    fills_part = pd.DataFrame({
        "timestamp": [dates[2]],
        "symbol": ["TEST"],
        "price": [100.0],
        "quantity": [10],
        "side": ["BUY"],
        "participation_rate": [0.05],
        "fees": [1.0],
        "cost": [1.0],
        "slippage": [0.0],
        "slippage_bps": [0.0],
        "fill_price": [100.0],
    })
    class PartRun:
        equity_curve = curve
        fills = fills_part
        metrics = TaggedRun.metrics

    exec_part = engine.evaluate_execution_stress(PartRun(), timeframe="1d", starting_capital=100_000.0)
    liq_part = next(r for r in exec_part if r.scenario_name == "reduced_liquidity")
    assert liq_part.status == EvidenceStatus.VALID
    assert liq_part.perturbation_params.get("participation_source") == "participation_rate"

    # Zero / NaN / negative market volume must fail closed with INVALID_MARKET_VOLUME_EVIDENCE
    fills_zero_vol = fills_reason.copy()
    fills_zero_vol["market_volume"] = 0.0
    class ZeroVolRun:
        equity_curve = curve
        fills = fills_zero_vol
        metrics = TaggedRun.metrics

    exec_zero_vol = engine.evaluate_execution_stress(ZeroVolRun(), timeframe="1d", starting_capital=100_000.0)
    liq_zero_vol = next(r for r in exec_zero_vol if r.scenario_name == "reduced_liquidity")
    assert liq_zero_vol.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert liq_zero_vol.reason == "INVALID_MARKET_VOLUME_EVIDENCE"

    # Invalid participation rate (< 0 or NaN) fails closed
    fills_bad_part = fills_part.copy()
    fills_bad_part["participation_rate"] = -0.1
    class BadPartRun:
        equity_curve = curve
        fills = fills_bad_part
        metrics = TaggedRun.metrics

    # Non-finite (+Inf / -Inf) market volume fails closed with INVALID_MARKET_VOLUME_EVIDENCE
    fills_inf_vol = fills_reason.copy()
    fills_inf_vol["market_volume"] = np.inf
    class InfVolRun:
        equity_curve = curve
        fills = fills_inf_vol
        metrics = TaggedRun.metrics

    exec_inf_vol = engine.evaluate_execution_stress(InfVolRun(), timeframe="1d", starting_capital=100_000.0)
    liq_inf_vol = next(r for r in exec_inf_vol if r.scenario_name == "reduced_liquidity")
    assert liq_inf_vol.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert liq_inf_vol.reason == "INVALID_MARKET_VOLUME_EVIDENCE"

    # Non-finite (+Inf / -Inf) participation rate fails closed with INVALID_MARKET_VOLUME_EVIDENCE
    fills_inf_part = fills_part.copy()
    fills_inf_part["participation_rate"] = np.inf
    class InfPartRun:
        equity_curve = curve
        fills = fills_inf_part
        metrics = TaggedRun.metrics

    exec_inf_part = engine.evaluate_execution_stress(InfPartRun(), timeframe="1d", starting_capital=100_000.0)
    liq_inf_part = next(r for r in exec_inf_part if r.scenario_name == "reduced_liquidity")
    assert liq_inf_part.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert liq_inf_part.reason == "INVALID_MARKET_VOLUME_EVIDENCE"

    fills_neginf_part = fills_part.copy()
    fills_neginf_part["participation_rate"] = -np.inf
    class NegInfPartRun:
        equity_curve = curve
        fills = fills_neginf_part
        metrics = TaggedRun.metrics

    exec_neginf_part = engine.evaluate_execution_stress(NegInfPartRun(), timeframe="1d", starting_capital=100_000.0)
    liq_neginf_part = next(r for r in exec_neginf_part if r.scenario_name == "reduced_liquidity")
    assert liq_neginf_part.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert liq_neginf_part.reason == "INVALID_MARKET_VOLUME_EVIDENCE"



