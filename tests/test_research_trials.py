"""Comprehensive test suite for Phase 2.1 Immutable Research Trial Registry."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from risk.engine import RiskEngine
from experiments.manager import ExperimentManager
from experiments.models import ExperimentSpec
from experiments.trials import (
    ExperimentFamilySpec,
    ResearchIntegrityError,
    ResearchLineageError,
    ResearchTrial,
)
from experiments.walk_forward import WalkForwardEvaluator
from research import main as research_cli_main
from storage.duckdb_manager import DuckDBManager
from trading_stack.domain import StrategyScope
from trading_stack.pipeline import DataQualityError as PipelineDataQualityError


@pytest.fixture
def test_db(tmp_path: Path) -> DuckDBManager:
    """Create a temporary initialized DuckDB with 014 migrations applied."""
    db_file = str(tmp_path / "research_trials_test.duckdb")
    db = DuckDBManager(db_file)
    from storage.migrations.runner import MigrationRunner
    MigrationRunner(db.conn).run_migrations()
    return db


@pytest.fixture
def sample_family() -> ExperimentFamilySpec:
    return ExperimentFamilySpec(
        experiment_family_id="fam_momentum_test",
        hypothesis="20-day momentum generates positive out-of-sample Sharpe on NIFTY 200.",
        strategy_names=["cross_sectional_momentum"],
        strategy_versions=["1.0.0"],
        universe_snapshot_id="NIFTY200_2026_08_17",
        timeframe="1d",
        feature_versions=["features-v1"],
        cost_model_version="angel-nse-delivery-2026-04",
        parameter_space={"lookback": [10, 20, 30], "skip_recent": [0, 5]},
        maximum_trials=10,
        selection_metric="sharpe",
        walk_forward_design={"train_size": 252, "test_size": 63},
        source_revision="rev-12345",
    )


# ---------------------------------------------------------------------------
# 1. Domain Validation & Deterministic Identity
# ---------------------------------------------------------------------------

def test_experiment_family_spec_validation(sample_family: ExperimentFamilySpec) -> None:
    assert sample_family.experiment_family_id == "fam_momentum_test"
    assert len(sample_family.definition_hash) == 64
    # Definition hash is deterministic
    clone = sample_family.model_copy()
    assert clone.definition_hash == sample_family.definition_hash


def test_research_trial_deterministic_hashing() -> None:
    trial1 = ResearchTrial(
        experiment_family_id="fam_1",
        strategy_name="trend_following",
        strategy_version="1.0.0",
        scope="SINGLE_ASSET",
        timeframe="1d",
        parameters={"lookback": 20, "atr_mult": 2.0},
        source_revision="rev_abc",
        data_hash="data_123",
        cost_model_hash="cost_456",
    )
    trial2 = ResearchTrial(
        experiment_family_id="fam_1",
        strategy_name="trend_following",
        strategy_version="1.0.0",
        scope="SINGLE_ASSET",
        timeframe="1d",
        parameters={"atr_mult": 2.0, "lookback": 20},  # Same parameters, different order
        source_revision="rev_abc",
        data_hash="data_123",
        cost_model_hash="cost_456",
    )
    assert trial1.trial_id == trial2.trial_id
    assert trial1.parameter_hash == trial2.parameter_hash

    # Changed parameter produces distinct trial ID
    trial3 = trial1.model_copy(update={"parameters": {"lookback": 30, "atr_mult": 2.0}})
    assert trial3.trial_id != trial1.trial_id

    # Changed strategy version produces distinct trial ID
    trial4 = trial1.model_copy(update={"strategy_version": "1.1.0"})
    assert trial4.trial_id != trial1.trial_id

    # Changed data hash produces distinct trial ID
    trial5 = trial1.model_copy(update={"data_hash": "data_999"})
    assert trial5.trial_id != trial1.trial_id

    # Changed timeframe produces distinct trial ID
    trial6 = trial1.model_copy(update={"timeframe": "1m"})
    assert trial6.trial_id != trial1.trial_id

    # Changed cost model hash produces distinct trial ID
    trial7 = trial1.model_copy(update={"cost_model_hash": "cost_999"})
    assert trial7.trial_id != trial1.trial_id

    # Changed fold ID produces distinct trial ID
    trial8 = trial1.model_copy(update={"fold_id": "wf-001"})
    assert trial8.trial_id != trial1.trial_id


# ---------------------------------------------------------------------------
# 2. Immutability & Budget Integrity
# ---------------------------------------------------------------------------

def test_experiment_family_immutability(test_db: DuckDBManager, sample_family: ExperimentFamilySpec) -> None:
    test_db.register_experiment_family(sample_family)
    
    # Idempotent re-registration of exact same definition is allowed
    test_db.register_experiment_family(sample_family)
    
    # Mutating material definition (e.g. hypothesis or strategy) raises ValueError
    tampered_family = sample_family.model_copy(update={"hypothesis": "Tampered hypothesis"})
    with pytest.raises(ValueError, match="material definition is immutable"):
        test_db.register_experiment_family(tampered_family)

    # Attempting to increase maximum_trials budget on existing family raises ValueError
    increased_budget_family = sample_family.model_copy(update={"maximum_trials": 100})
    with pytest.raises(ValueError, match="material definition is immutable"):
        test_db.register_experiment_family(increased_budget_family)


# ---------------------------------------------------------------------------
# 3. Lifecycle States & Invalidation
# ---------------------------------------------------------------------------

def test_research_trial_lifecycle_and_invalidation(test_db: DuckDBManager, sample_family: ExperimentFamilySpec) -> None:
    test_db.register_experiment_family(sample_family)
    trial = ResearchTrial(
        experiment_family_id=sample_family.experiment_family_id,
        strategy_name="cross_sectional_momentum",
        strategy_version="1.0.0",
        scope="CROSS_SECTIONAL_PORTFOLIO",
        timeframe="1d",
        parameters={"lookback": 20},
        source_revision="rev-12345",
        data_hash="data-hash-01",
        cost_model_hash="cost-hash-01",
        frame_certification_id="frame-cert-01",
    )
    
    trial_id = test_db.create_research_trial(trial)
    t = test_db.get_research_trial(trial_id)
    assert t is not None
    assert t["status"] == "PLANNED"

    # Transition to RUNNING
    test_db.transition_research_trial(trial_id, "RUNNING")
    t = test_db.get_research_trial(trial_id)
    assert t["status"] == "RUNNING"
    assert t["started_at"] is not None

    # Transition to SUCCEEDED with metrics
    test_db.transition_research_trial(trial_id, "SUCCEEDED", metrics={"sharpe": 1.45, "max_drawdown": 0.12})
    t = test_db.get_research_trial(trial_id)
    assert t["status"] == "SUCCEEDED"
    assert t["metrics"]["sharpe"] == 1.45
    assert t["finished_at"] is not None

    # Marking selected
    test_db.mark_trial_selected(trial_id, True)
    t = test_db.get_research_trial(trial_id)
    assert t["selected"] is True

    # Invalidate trial without deleting it
    test_db.invalidate_trial(trial_id, reason="DATA_BUG")
    t = test_db.get_research_trial(trial_id)
    assert t["status"] == "INVALIDATED"
    assert t["invalidation_reason"] == "DATA_BUG"
    assert t["invalidated_at"] is not None
    assert t["metrics"]["sharpe"] == 1.45  # Metrics preserved forensically


# ---------------------------------------------------------------------------
# 4. Budget Enforcement & Atomic Concurrency
# ---------------------------------------------------------------------------

def test_pre_evaluation_budget_enforcement(test_db: DuckDBManager) -> None:
    family = ExperimentFamilySpec(
        experiment_family_id="fam_budget_small",
        hypothesis="Small budget test",
        strategy_names=["trend_following"],
        strategy_versions=["1.0.0"],
        universe_snapshot_id="NIFTY200_2026_08_17",
        timeframe="1d",
        feature_versions=["features-v1"],
        cost_model_version="angel-nse-delivery-2026-04",
        parameter_space={"lookback": [10, 20]},
        maximum_trials=2,
        selection_metric="sharpe",
        walk_forward_design={"train_size": 252, "test_size": 63},
        source_revision="rev-1",
    )
    test_db.register_experiment_family(family)

    # Reserve Slot 1
    t1 = ResearchTrial(
        experiment_family_id="fam_budget_small", strategy_name="trend_following",
        strategy_version="1.0.0", scope="SINGLE_ASSET", timeframe="1d",
        parameters={"lookback": 10}, source_revision="rev-1",
        data_hash="d1", cost_model_hash="c1",
    )
    test_db.create_research_trial(t1)

    # Reserve Slot 2
    t2 = ResearchTrial(
        experiment_family_id="fam_budget_small", strategy_name="trend_following",
        strategy_version="1.0.0", scope="SINGLE_ASSET", timeframe="1d",
        parameters={"lookback": 20}, source_revision="rev-1",
        data_hash="d1", cost_model_hash="c1",
    )
    test_db.create_research_trial(t2)

    assert test_db.remaining_trial_budget("fam_budget_small") == 0

    # Attempt Slot 3 -> Must fail closed BEFORE candidate execution
    t3 = ResearchTrial(
        experiment_family_id="fam_budget_small", strategy_name="trend_following",
        strategy_version="1.0.0", scope="SINGLE_ASSET", timeframe="1d",
        parameters={"lookback": 30}, source_revision="rev-1",
        data_hash="d1", cost_model_hash="c1",
    )
    with pytest.raises(RuntimeError, match="trial budget exhausted"):
        test_db.create_research_trial(t3)


def test_concurrent_budget_reservation_atomicity(tmp_path: Path) -> None:
    db_file = str(tmp_path / "concurrent_budget.duckdb")
    db = DuckDBManager(db_file)
    from storage.migrations.runner import MigrationRunner
    MigrationRunner(db.conn).run_migrations()

    family = ExperimentFamilySpec(
        experiment_family_id="fam_concurrent",
        hypothesis="Concurrent budget race test",
        strategy_names=["trend_following"],
        strategy_versions=["1.0.0"],
        universe_snapshot_id="NIFTY200_2026_08_17",
        timeframe="1d",
        feature_versions=["features-v1"],
        cost_model_version="angel-nse-delivery-2026-04",
        parameter_space={"lookback": list(range(50))},
        maximum_trials=5,
        selection_metric="sharpe",
        walk_forward_design={"train_size": 252, "test_size": 63},
        source_revision="rev-1",
    )
    db.register_experiment_family(family)
    db.close()

    def attempt_reservation(param_idx: int) -> bool:
        local_db = DuckDBManager(db_file)
        trial = ResearchTrial(
            experiment_family_id="fam_concurrent",
            strategy_name="trend_following",
            strategy_version="1.0.0",
            scope="SINGLE_ASSET",
            timeframe="1d",
            parameters={"lookback": param_idx},
            source_revision="rev-1",
            data_hash="d1",
            cost_model_hash="c1",
        )
        try:
            local_db.create_research_trial(trial)
            return True
        except RuntimeError:
            return False
        finally:
            local_db.close()

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt_reservation, range(20)))

    # Exactly 5 reservations succeeded, 15 failed
    assert sum(results) == 5

    verify_db = DuckDBManager(db_file)
    summary = verify_db.research_trial_summary("fam_concurrent")
    assert summary["consumed"] == 5
    assert summary["remaining"] == 0
    verify_db.close()


# ---------------------------------------------------------------------------
# 5. Interrupted Process Recovery
# ---------------------------------------------------------------------------

def test_interrupted_process_recovery(test_db: DuckDBManager, sample_family: ExperimentFamilySpec) -> None:
    test_db.register_experiment_family(sample_family)
    trial = ResearchTrial(
        experiment_family_id=sample_family.experiment_family_id,
        strategy_name="cross_sectional_momentum",
        strategy_version="1.0.0",
        scope="CROSS_SECTIONAL_PORTFOLIO",
        timeframe="1d",
        parameters={"lookback": 20},
        source_revision="rev-12345",
        data_hash="d1",
        cost_model_hash="c1",
        frame_certification_id="frame-cert-cli",
    )
    trial_id = test_db.create_research_trial(trial)
    test_db.transition_research_trial(trial_id, "RUNNING")

    # Simulate host restart / recovery
    recovered_count = test_db.recover_interrupted_research_trials()
    assert recovered_count >= 1

    t = test_db.get_research_trial(trial_id)
    assert t["status"] == "FAILED"
    assert t["error_message"] == "INTERRUPTED_PROCESS"
    assert t["finished_at"] is not None


# ---------------------------------------------------------------------------
# 6. WalkForwardEvaluator Candidate-Level Accounting & Retention
# ---------------------------------------------------------------------------

class MockMetrics:
    def __init__(self, sharpe: float, max_drawdown: float = 0.10, cagr: float = 0.15, total_return: float = 0.25) -> None:
        self.sharpe = sharpe
        self.max_drawdown = max_drawdown
        self.cagr = cagr
        self.total_return = total_return


class MockRunResult:
    def __init__(self, sharpe: float, max_drawdown: float = 0.10, run_id: str = "run_0") -> None:
        self.metrics = MockMetrics(sharpe=sharpe, max_drawdown=max_drawdown)
        self.run_id = run_id


def test_walk_forward_evaluator_records_every_candidate(test_db: DuckDBManager) -> None:
    family = ExperimentFamilySpec(
        experiment_family_id="fam_wf_candidates",
        hypothesis="Candidate-level recording test",
        strategy_names=["trend_following"],
        strategy_versions=["1.0.0"],
        universe_snapshot_id="NIFTY200_2026_08_17",
        timeframe="1d",
        feature_versions=["features-v1"],
        cost_model_version="angel-nse-delivery-2026-04",
        parameter_space={"lookback": [10, 20, 30]},
        maximum_trials=10,
        selection_metric="sharpe",
        walk_forward_design={"train_size": 252, "test_size": 63},
        source_revision="rev-1",
    )
    test_db.register_experiment_family(family)

    evaluator = WalkForwardEvaluator(test_db, maximum_candidates=3, risk_engine=RiskEngine())
    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["RELIANCE"],
        timeframe="1d",
        parameters={"lookback": 20},
        experiment_family_id="fam_wf_candidates",
    )

    # Mock _run to return custom metrics for 3 candidates
    scores = [0.5, 1.8, -0.2]  # Candidate 2 (lookback: 20) will win
    call_count = 0

    def mock_run(s: Any, scope: Any, src: Any, params: dict[str, Any], cap: float) -> Any:
        nonlocal call_count
        score = scores[call_count % len(scores)]
        res = MockRunResult(sharpe=score, run_id=f"run_{call_count}")
        call_count += 1
        return res

    mock_source = MagicMock()
    mock_source.data_hash = "mock_data_hash"
    mock_source.frame_certification_id = "cert_123"
    mock_source.panel = pd.DataFrame({"timestamp": [pd.Timestamp("2026-01-01", tz="UTC")]})

    candidates = [{"lookback": 10}, {"lookback": 20}, {"lookback": 30}]

    with patch.object(evaluator, "_run", side_effect=mock_run):
        best_params, best_score = evaluator._select(
            spec, StrategyScope.SINGLE_ASSET, mock_source, candidates, 100_000.0, fold_id="wf-001"
        )

    assert best_params == {"lookback": 20}
    assert best_score == 1.8
    assert call_count == 3

    trials = test_db.list_research_trials("fam_wf_candidates")
    assert len(trials) == 3

    # 2 losing trials retained as SUCCEEDED with selected = False
    losing_trials = [t for t in trials if not t["selected"]]
    assert len(losing_trials) == 2
    for lt in losing_trials:
        assert lt["status"] == "SUCCEEDED"
        assert lt["metrics"] is not None

    # 1 winning trial marked as selected = True
    winning_trials = [t for t in trials if t["selected"]]
    assert len(winning_trials) == 1
    assert winning_trials[0]["parameters"] == {"lookback": 20}
    assert winning_trials[0]["metrics"]["sharpe"] == 1.8


def test_walk_forward_budget_exhaustion_blocks_candidate_execution(test_db: DuckDBManager) -> None:
    family = ExperimentFamilySpec(
        experiment_family_id="fam_wf_budget_block",
        hypothesis="Budget exhaustion blocking candidate execution",
        strategy_names=["trend_following"],
        strategy_versions=["1.0.0"],
        universe_snapshot_id="NIFTY200_2026_08_17",
        timeframe="1d",
        feature_versions=["features-v1"],
        cost_model_version="angel-nse-delivery-2026-04",
        parameter_space={"lookback": [10, 20, 30]},
        maximum_trials=2,  # Only 2 allowed!
        selection_metric="sharpe",
        walk_forward_design={"train_size": 252, "test_size": 63},
        source_revision="rev-1",
    )
    test_db.register_experiment_family(family)

    evaluator = WalkForwardEvaluator(test_db, maximum_candidates=5, risk_engine=RiskEngine())
    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["RELIANCE"],
        timeframe="1d",
        parameters={"lookback": 20},
        experiment_family_id="fam_wf_budget_block",
    )

    execution_count = 0

    def mock_run(s: Any, scope: Any, src: Any, params: dict[str, Any], cap: float) -> Any:
        nonlocal execution_count
        execution_count += 1
        return MockRunResult(sharpe=1.0, max_drawdown=0.10, run_id=f"run_{execution_count}")

    mock_source = MagicMock()
    mock_source.data_hash = "mock_data_hash"
    mock_source.frame_certification_id = "cert_123"
    mock_source.panel = pd.DataFrame({"timestamp": [pd.Timestamp("2026-01-01", tz="UTC")]})

    candidates = [{"lookback": 10}, {"lookback": 20}, {"lookback": 30}]

    with patch.object(evaluator, "_run", side_effect=mock_run):
        # Candidate 3 should trigger budget exhaustion before executing _run
        with pytest.raises(RuntimeError, match="trial budget exhausted"):
            evaluator._select(spec, StrategyScope.SINGLE_ASSET, mock_source, candidates, 100_000.0)

    # Actual candidate execution count must be exactly maximum_trials = 2
    assert execution_count == 2
    # Candidate 3 was NEVER executed!


# ---------------------------------------------------------------------------
# 7. ExperimentManager & MassExperimentManager Integration
# ---------------------------------------------------------------------------

def test_experiment_manager_failure_retention(test_db: DuckDBManager, sample_family: ExperimentFamilySpec) -> None:
    test_db.register_experiment_family(sample_family)
    mgr = ExperimentManager(test_db)
    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["UNKNOWN_SYMBOL_XYZ"],
        timeframe="1d",
        parameters={"lookback": 20},
        experiment_family_id=sample_family.experiment_family_id,
        require_authoritative_certification=False,
    )

    with pytest.raises(Exception):
        mgr.run(spec)

    trials = test_db.list_research_trials(sample_family.experiment_family_id)
    assert len(trials) == 1
    assert trials[0]["status"] == "FAILED"
    assert trials[0]["error_message"] is not None


# ---------------------------------------------------------------------------
# 8. Read-Only Research-Trials CLI
# ---------------------------------------------------------------------------

def test_research_trials_cli(test_db: DuckDBManager, sample_family: ExperimentFamilySpec, capsys: pytest.CaptureFixture[str]) -> None:
    test_db.register_experiment_family(sample_family)
    trial = ResearchTrial(
        experiment_family_id=sample_family.experiment_family_id,
        strategy_name="cross_sectional_momentum",
        strategy_version="1.0.0",
        scope="CROSS_SECTIONAL_PORTFOLIO",
        timeframe="1d",
        parameters={"lookback": 20},
        source_revision="rev-12345",
        data_hash="d1",
        cost_model_hash="c1",
        frame_certification_id="frame-cert-cli",
    )
    trial_id = test_db.create_research_trial(trial)
    test_db.transition_research_trial(trial_id, "SUCCEEDED", metrics={"sharpe": 1.25})

    mock_config = {
        "database": {"path": str(test_db.db_path)},
        "smartapi": {
            "api_key": "mock_key", "client_code": "mock_client", "pin": "1234",
            "totp_secret": "mock_totp", "base_url": "https://apiconnect.angelone.in",
            "instrument_master_url": "https://margincalculator.angelbroking.com",
        },
        "logging": {"path": "logs", "level": "INFO", "rotation": "10 MB", "retention": "7 days"},
        "rate_limits": {
            "requests_per_second": 3, "requests_per_minute": 180, "chunk_days_1min": 60,
            "chunk_days_1day": 2000, "retry_max_attempts": 3, "retry_wait_seconds": 1, "retry_max_wait_seconds": 10,
        },
        "data": {"start_date": "2020-01-01", "timeframes": [{"interval": "1d", "label": "1d"}], "instrument_master_refresh_hours": 24},
        "timezone": {"market_tz": "Asia/Kolkata", "market_open": "09:15", "market_close": "15:30"},
        "research": {},
    }
    mock_symbols = {"symbols": [{"symbol": "RELIANCE", "token": "2885", "exchange": "NSE", "instrument_type": "EQUITY"}]}

    def mock_load_yaml(path: str) -> Any:
        if "symbols.yaml" in path:
            return mock_symbols
        return mock_config

    # Test summary view for family
    with patch("research.load_yaml", side_effect=mock_load_yaml), \
         patch("research.validate_config", return_value=None), \
         patch("research.DuckDBManager", side_effect=lambda path: DuckDBManager(test_db.db_path)):
        ret = research_cli_main(["--command", "research-trials", "--experiment-family-id", sample_family.experiment_family_id])
        assert ret == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["family_id"] == sample_family.experiment_family_id
        assert data["summary"]["consumed"] == 1
        assert len(data["trials"]) == 1

    # Test single trial view
    with patch("research.load_yaml", side_effect=mock_load_yaml), \
         patch("research.validate_config", return_value=None), \
         patch("research.DuckDBManager", side_effect=lambda path: DuckDBManager(test_db.db_path)):
        ret = research_cli_main(["--command", "research-trials", "--trial-id", trial_id])
        assert ret == 0
        captured = capsys.readouterr()
        trial_data = json.loads(captured.out)
        assert trial_data["trial_id"] == trial_id
        assert trial_data["status"] == "SUCCEEDED"


# ---------------------------------------------------------------------------
# 9. Statistical Integrity Acceptance Test (Section 28)
# ---------------------------------------------------------------------------

def test_statistical_integrity_acceptance_20_candidates(test_db: DuckDBManager) -> None:
    """Demonstrates that 20 candidate evaluations are fully persisted, with 19 losing trials retained, 1 selected, and candidate 21 blocked."""
    family = ExperimentFamilySpec(
        experiment_family_id="fam_dsr_accounting_20",
        hypothesis="Multiple-testing accounting over 20 parameter configurations",
        strategy_names=["trend_following"],
        strategy_versions=["1.0.0"],
        universe_snapshot_id="NIFTY200_2026_08_17",
        timeframe="1d",
        feature_versions=["features-v1"],
        cost_model_version="angel-nse-delivery-2026-04",
        parameter_space={"lookback": list(range(1, 21))},
        maximum_trials=20,
        selection_metric="sharpe",
        walk_forward_design={"train_size": 252, "test_size": 63},
        source_revision="rev-acceptance",
    )
    test_db.register_experiment_family(family)

    evaluator = WalkForwardEvaluator(test_db, maximum_candidates=30, risk_engine=RiskEngine())
    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["RELIANCE"],
        timeframe="1d",
        parameters={},
        experiment_family_id="fam_dsr_accounting_20",
    )

    candidate_count = 0

    def mock_eval(s: Any, scope: Any, src: Any, params: dict[str, Any], cap: float) -> Any:
        nonlocal candidate_count
        candidate_count += 1
        # Candidate 15 has highest Sharpe = 2.5
        sharpe = 2.5 if params.get("lookback") == 15 else float(params.get("lookback", 1)) * 0.05
        return MockRunResult(sharpe=sharpe, max_drawdown=0.12, run_id=f"run_{candidate_count}")

    mock_source = MagicMock()
    mock_source.data_hash = "hash_acceptance"
    mock_source.frame_certification_id = "cert_acceptance"
    mock_source.panel = pd.DataFrame({"timestamp": [pd.Timestamp("2026-01-01", tz="UTC")]})

    candidates = [{"lookback": i} for i in range(1, 21)]

    with patch.object(evaluator, "_run", side_effect=mock_eval):
        best_params, best_score = evaluator._select(
            spec, StrategyScope.SINGLE_ASSET, mock_source, candidates, 100_000.0, fold_id="wf-001"
        )

    assert best_params == {"lookback": 15}
    assert best_score == 2.5
    assert candidate_count == 20

    # Verify DuckDB persistence
    trials = test_db.list_research_trials("fam_dsr_accounting_20")
    assert len(trials) == 20

    # 19 losing trials retained
    losing_trials = [t for t in trials if not t["selected"]]
    assert len(losing_trials) == 19
    for t in losing_trials:
        assert t["status"] == "SUCCEEDED"
        assert t["metrics"] is not None

    # 1 winning/selected trial marked
    winning_trials = [t for t in trials if t["selected"]]
    assert len(winning_trials) == 1
    assert winning_trials[0]["parameters"] == {"lookback": 15}

    # Summary reflects 20 consumed, 0 remaining
    summary = test_db.research_trial_summary("fam_dsr_accounting_20")
    assert summary["consumed"] == 20
    assert summary["remaining"] == 0
    assert summary["selected_count"] == 1

    # Candidate 21 must be rejected by budget
    candidate_21 = ResearchTrial(
        experiment_family_id="fam_dsr_accounting_20",
        strategy_name="trend_following",
        strategy_version="1.0.0",
        scope="SINGLE_ASSET",
        timeframe="1d",
        parameters={"lookback": 21},
        source_revision="rev-acceptance",
        data_hash="hash_acceptance",
        cost_model_hash="c1",
    )
    with pytest.raises(RuntimeError, match="trial budget exhausted"):
        test_db.create_research_trial(candidate_21)


# ---------------------------------------------------------------------------
# 10. Forensic Integrity & Lineage Integration Tests
# ---------------------------------------------------------------------------

def test_adversarial_market_data_lineage_distinct_trial_identity() -> None:
    """Adversarial test: same strategy, same parameters, same universe, different dataset content hash => distinct research trial."""
    trial_dataset_v1 = ResearchTrial(
        experiment_family_id="fam_lineage_test",
        strategy_name="trend_following",
        strategy_version="1.0.0",
        scope="SINGLE_ASSET",
        symbol="RELIANCE",
        timeframe="1d",
        parameters={"lookback": 20},
        source_revision="rev_lineage_1",
        data_hash="data_hash_content_v1",  # Initial dataset content hash
        cost_model_hash="cost_model_v1",
    )

    trial_dataset_v2 = ResearchTrial(
        experiment_family_id="fam_lineage_test",
        strategy_name="trend_following",
        strategy_version="1.0.0",
        scope="SINGLE_ASSET",
        symbol="RELIANCE",
        timeframe="1d",
        parameters={"lookback": 20},
        source_revision="rev_lineage_1",
        data_hash="data_hash_content_v2",  # Changed market data content hash!
        cost_model_hash="cost_model_v1",
    )

    # Invariant: Changing market data while keeping same universe MUST create distinct research trial identity
    assert trial_dataset_v1.trial_id != trial_dataset_v2.trial_id
    assert trial_dataset_v1.data_hash != trial_dataset_v2.data_hash


def test_walk_forward_evaluator_failed_candidate_continuation(test_db: DuckDBManager) -> None:
    """A succeeds, B raises exception -> B retained as FAILED, C succeeds with highest Sharpe -> C SUCCEEDED + selected."""
    family = ExperimentFamilySpec(
        experiment_family_id="fam_wf_continuation",
        hypothesis="Candidate B failure does not abort candidate C evaluation",
        strategy_names=["trend_following"],
        strategy_versions=["1.0.0"],
        universe_snapshot_id="NIFTY200_2026_08_17",
        timeframe="1d",
        feature_versions=["features-v1"],
        cost_model_version="angel-nse-delivery-2026-04",
        parameter_space={"lookback": [10, 20, 30]},
        maximum_trials=5,
        selection_metric="sharpe",
        walk_forward_design={"train_size": 252, "test_size": 63},
        source_revision="rev-wf-cont",
    )
    test_db.register_experiment_family(family)

    evaluator = WalkForwardEvaluator(test_db, maximum_candidates=5, risk_engine=RiskEngine())
    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["RELIANCE"],
        timeframe="1d",
        parameters={},
        experiment_family_id="fam_wf_continuation",
    )

    call_count = 0

    def mock_run_with_failure(s: Any, scope: Any, src: Any, params: dict[str, Any], cap: float) -> Any:
        nonlocal call_count
        call_count += 1
        lookback = params.get("lookback")
        if lookback == 10:
            # Candidate A succeeds (Sharpe = 1.0)
            return MockRunResult(sharpe=1.0, max_drawdown=0.10, run_id="run_a")
        elif lookback == 20:
            # Candidate B raises candidate-local evaluation exception
            raise ValueError("Division by zero in indicator calculation for candidate B")
        elif lookback == 30:
            # Candidate C succeeds with highest Sharpe (Sharpe = 2.2)
            return MockRunResult(sharpe=2.2, max_drawdown=0.08, run_id="run_c")
        return MockRunResult(sharpe=0.5, max_drawdown=0.15, run_id=f"run_{call_count}")

    mock_source = MagicMock()
    mock_source.data_hash = "mock_source_data_hash"
    mock_source.frame_certification_id = "cert_wf_cont"
    mock_source.panel = pd.DataFrame({"timestamp": [pd.Timestamp("2026-01-01", tz="UTC")]})

    candidates = [{"lookback": 10}, {"lookback": 20}, {"lookback": 30}]

    with patch.object(evaluator, "_run", side_effect=mock_run_with_failure):
        best_params, best_score = evaluator._select(
            spec, StrategyScope.SINGLE_ASSET, mock_source, candidates, 100_000.0, fold_id="wf-001"
        )

    # Invariant: Selection continued across candidate B failure and picked Candidate C
    assert best_params == {"lookback": 30}
    assert best_score == 2.2

    # Verify all 3 trials are persisted in DuckDB
    trials = test_db.list_research_trials("fam_wf_continuation")
    assert len(trials) == 3

    # Trial A: lookback 10 -> SUCCEEDED, selected = False
    trial_a = next(t for t in trials if t["parameters"] == {"lookback": 10})
    assert trial_a["status"] == "SUCCEEDED"
    assert trial_a["selected"] is False
    assert trial_a["metrics"]["sharpe"] == 1.0

    # Trial B: lookback 20 -> FAILED, error_message recorded, selected = False
    trial_b = next(t for t in trials if t["parameters"] == {"lookback": 20})
    assert trial_b["status"] == "FAILED"
    assert trial_b["selected"] is False
    assert "Division by zero" in str(trial_b["error_message"])

    # Trial C: lookback 30 -> SUCCEEDED, selected = True
    trial_c = next(t for t in trials if t["parameters"] == {"lookback": 30})
    assert trial_c["status"] == "SUCCEEDED"
    assert trial_c["selected"] is True
    assert trial_c["metrics"]["sharpe"] == 2.2


def test_failed_trial_retry_and_exact_succeeded_resume_semantics(test_db: DuckDBManager, sample_family: ExperimentFamilySpec) -> None:
    """Proves: attempt 1 -> FAILED, attempt 2 -> executes, both attempts retained, budget count = 2. Exact SUCCEEDED resume does NOT add a new trial."""
    test_db.register_experiment_family(sample_family)

    base_trial = ResearchTrial(
        experiment_family_id=sample_family.experiment_family_id,
        strategy_name="cross_sectional_momentum",
        strategy_version="1.0.0",
        scope="CROSS_SECTIONAL_PORTFOLIO",
        timeframe="1d",
        parameters={"lookback": 20},
        source_revision="rev-retry-test",
        data_hash="data-retry-hash",
        cost_model_hash="cost-retry-hash",
        frame_certification_id="frame-cert-retry",
    )

    # 1. Attempt 1: created, runs, and fails
    trial_id_1 = test_db.create_research_trial(base_trial)
    test_db.transition_research_trial(trial_id_1, "RUNNING")
    test_db.transition_research_trial(trial_id_1, "FAILED", error_message="Execution timeout on node 1")

    assert test_db.remaining_trial_budget(sample_family.experiment_family_id) == sample_family.maximum_trials - 1

    # 2. Attempt 2 (retry after failure): must create a NEW attempt and consume budget
    trial_id_2 = test_db.create_research_trial(base_trial)
    assert trial_id_2 != trial_id_1
    assert "#attempt=2" in trial_id_2

    test_db.transition_research_trial(trial_id_2, "RUNNING")
    test_db.transition_research_trial(trial_id_2, "SUCCEEDED", metrics={"sharpe": 1.75, "max_drawdown": 0.11})

    # Both attempts are retained, budget consumed is 2
    summary = test_db.research_trial_summary(sample_family.experiment_family_id)
    assert summary["consumed"] == 2
    assert summary["remaining"] == sample_family.maximum_trials - 2

    t1 = test_db.get_research_trial(trial_id_1)
    t2 = test_db.get_research_trial(trial_id_2)
    assert t1 is not None and t1["status"] == "FAILED"
    assert t2 is not None and t2["status"] == "SUCCEEDED"
    assert t2["parent_trial_id"] == trial_id_1

    # 3. Exact SUCCEEDED resume does NOT create a false new trial or consume extra budget
    trial_id_3 = test_db.create_research_trial(base_trial)
    # Reuses existing successful trial
    assert trial_id_3 == trial_id_1 or trial_id_3 == trial_id_2
    summary_after_resume = test_db.research_trial_summary(sample_family.experiment_family_id)
    assert summary_after_resume["consumed"] == 2  # Budget unchanged!


def test_mass_experiment_manager_family_propagation(test_db: DuckDBManager) -> None:
    """Verifies that MassExperimentManager propagates experiment_family_id to child ExperimentSpecs."""
    family = ExperimentFamilySpec(
        experiment_family_id="fam_mass_prop",
        hypothesis="Mass experiment family propagation test",
        strategy_names=["trend_following"],
        strategy_versions=["1.0.0"],
        universe_snapshot_id="NIFTY200_2026_08_17",
        timeframe="1d",
        feature_versions=["features-v1"],
        cost_model_version="angel-nse-delivery-2026-04",
        parameter_space={"trend_following": {"lookback": 20}},
        maximum_trials=5,
        selection_metric="sharpe",
        walk_forward_design={"train_size": 252, "test_size": 63},
        source_revision="rev-mass-prop",
    )
    test_db.register_experiment_family(family)

    from experiments.mass import MassExperimentManager
    from experiments.models import MassExperimentSpec

    mgr = MassExperimentManager(test_db)
    spec = MassExperimentSpec(
        experiment_id="mass_exp_test",
        strategy_names=["trend_following"],
        universe=["INFY"],
        timeframe="1d",
        parameters={"trend_following": {"lookback": 20}},
        experiment_family_id="fam_mass_prop",
        require_authoritative_certification=False,
    )

    executed_spec_family_ids: list[str | None] = []

    def mock_manager_run(child_spec: ExperimentSpec, starting_capital: float = 100000.0) -> dict[str, Any]:
        executed_spec_family_ids.append(child_spec.experiment_family_id)
        mock_result = MagicMock()
        mock_result.run_id = "run_mass_01"
        mock_result.data_hash = "mass_data_hash"
        mock_result.metrics.sharpe = 1.3
        mock_result.metrics.max_drawdown = 0.12
        return {"experiment_id": child_spec.experiment_id, "outcome": {"result": mock_result}}

    with patch.object(ExperimentManager, "run", side_effect=mock_manager_run), \
         patch.object(WalkForwardEvaluator, "evaluate", return_value=[{"fold": 1}]):
        res = mgr.run(spec)

    # Verify family ID was propagated to child experiment spec
    assert len(executed_spec_family_ids) == 1
    assert executed_spec_family_ids[0] == "fam_mass_prop"
    assert res["jobs"][0]["state"] == "SUCCEEDED"


def test_experiment_manager_successful_execution_and_metrics_linkage(test_db: DuckDBManager, sample_family: ExperimentFamilySpec) -> None:
    """Verifies that ExperimentManager successful execution transitions trial to SUCCEEDED and binds metrics & run_id."""
    test_db.register_experiment_family(sample_family)
    mgr = ExperimentManager(test_db)
    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["TCS"],
        timeframe="1d",
        parameters={"lookback": 20},
        experiment_family_id=sample_family.experiment_family_id,
        require_authoritative_certification=False,
    )

    mock_run_result = MockRunResult(sharpe=1.65, max_drawdown=0.09, run_id="run_exp_success_001")
    mock_run_result.data_hash = "mock_exp_data_hash"

    with patch.object(mgr, "_record_dataset_group", return_value="ds_group_1"), \
         patch.object(mgr, "_latest_dataset_id", return_value="ds_single_1"), \
         patch("experiments.manager.StrategyPipeline") as mock_pipeline_cls:
        mock_pipeline = MagicMock()
        mock_pipeline.load_candles.return_value = pd.DataFrame({
            "timestamp": [pd.Timestamp("2026-01-01", tz="UTC")],
            "open": [100.0], "high": [105.0], "low": [98.0], "close": [102.0], "volume": [1000],
        })
        mock_pipeline._last_frame_certification_id = "cert_exp_001"
        mock_pipeline.run.return_value = {"result": mock_run_result}
        mock_pipeline_cls.return_value = mock_pipeline

        res = mgr.run(spec)

    assert res["experiment_id"] == spec.experiment_id

    trials = test_db.list_research_trials(sample_family.experiment_family_id)
    assert len(trials) == 1
    trial = trials[0]
    assert trial["status"] == "SUCCEEDED"
    assert trial["metrics"] is not None
    assert trial["metrics"]["sharpe"] == 1.65
    assert trial["metrics"]["run_id"] == "run_exp_success_001"
    assert trial["finished_at"] is not None


def test_governed_lineage_failure_is_retained_without_execution(
    test_db: DuckDBManager, sample_family: ExperimentFamilySpec,
) -> None:
    """A later executable result cannot turn an unresolved governed attempt into success."""

    test_db.register_experiment_family(sample_family)
    manager = ExperimentManager(test_db)
    spec = ExperimentSpec(
        strategy_name="trend_following",
        universe=["RELIANCE"],
        timeframe="1d",
        parameters={"lookback": 20},
        experiment_family_id=sample_family.experiment_family_id,
        require_authoritative_certification=False,
    )
    pipeline = MagicMock()
    pipeline.load_candles.side_effect = PipelineDataQualityError("missing certified dataset")
    pipeline.run.return_value = {"result": MockRunResult(sharpe=3.0, run_id="must-not-run")}

    with patch("experiments.manager.StrategyPipeline", return_value=pipeline):
        with pytest.raises(ResearchLineageError, match="lineage resolution failed"):
            manager.run(spec)

    assert pipeline.run.call_count == 0
    trials = test_db.list_research_trials(sample_family.experiment_family_id)
    assert len(trials) == 1
    assert trials[0]["status"] == "FAILED"
    assert str(trials[0]["data_hash"]).startswith("unresolved:")


def test_storage_rejects_unresolved_or_missing_lineage_success(
    test_db: DuckDBManager, sample_family: ExperimentFamilySpec,
) -> None:
    """The ledger independently blocks fail-open success and selection transitions."""

    test_db.register_experiment_family(sample_family)
    unresolved = ResearchTrial(
        experiment_family_id=sample_family.experiment_family_id,
        strategy_name="trend_following", strategy_version="1.0.0", scope="SINGLE_ASSET",
        timeframe="1d", parameters={"lookback": 10}, source_revision="rev",
        data_hash="unresolved:lineage", cost_model_hash="cost",
    )
    unresolved_id = test_db.create_research_trial(unresolved)
    test_db.transition_research_trial(unresolved_id, "RUNNING")
    with pytest.raises(ValueError, match="resolved data hash"):
        test_db.transition_research_trial(unresolved_id, "SUCCEEDED")
    with pytest.raises(ValueError, match="Only SUCCEEDED"):
        test_db.mark_trial_selected(unresolved_id)

    missing_frame = unresolved.model_copy(update={"parameters": {"lookback": 20}, "data_hash": "valid-hash"})
    missing_frame_id = test_db.create_research_trial(missing_frame)
    with pytest.raises(ValueError, match="resolved data hash"):
        test_db.transition_research_trial(missing_frame_id, "SUCCEEDED")


def test_migration_invalidates_historical_unresolved_success(
    test_db: DuckDBManager, sample_family: ExperimentFamilySpec,
) -> None:
    """Migration 015 preserves, but invalidates, legacy successful unresolved lineage."""

    test_db.register_experiment_family(sample_family)
    test_db.conn.execute(
        """INSERT INTO research_trials_log (
            trial_id, experiment_family_id, status, trial_json, created_at, selected
        ) VALUES (?, ?, 'SUCCEEDED', ?, CURRENT_TIMESTAMP, TRUE)""",
        [
            "legacy-unresolved-success",
            sample_family.experiment_family_id,
            json.dumps({"data_hash": "unresolved:legacy", "frame_certification_id": None}),
        ],
    )
    test_db.conn.execute(
        (Path("storage/migrations/015_invalidate_unresolved_research_trials.sql")).read_text(encoding="utf-8")
    )
    migrated = test_db.get_research_trial("legacy-unresolved-success")
    assert migrated is not None
    assert migrated["status"] == "INVALIDATED"
    assert migrated["selected"] is False
    assert migrated["invalidation_reason"] == "UNRESOLVED_LINEAGE_HISTORICAL_REMEDIATION"


def test_walk_forward_governance_failure_aborts_before_candidate_c(
    test_db: DuckDBManager,
) -> None:
    """Candidate-local failures continue; DQ/certification failures abort the search."""

    family = ExperimentFamilySpec(
        experiment_family_id="fam_wf_governance_abort", hypothesis="Fail closed on DQ failure",
        strategy_names=["trend_following"], strategy_versions=["1.0.0"],
        universe_snapshot_id="NIFTY200_2026_08_17", timeframe="1d",
        feature_versions=["features-v1"], cost_model_version="cost-v1",
        parameter_space={"lookback": [10, 20, 30]}, maximum_trials=5,
        selection_metric="sharpe", walk_forward_design={"train_size": 252, "test_size": 63},
        source_revision="rev",
    )
    test_db.register_experiment_family(family)
    evaluator = WalkForwardEvaluator(test_db, maximum_candidates=3, risk_engine=RiskEngine())
    spec = ExperimentSpec(
        strategy_name="trend_following", universe=["RELIANCE"], timeframe="1d",
        experiment_family_id=family.experiment_family_id,
    )
    source = MagicMock()
    source.data_hash = "resolved-source-hash"
    source.frame_certification_id = "frame-cert"
    source.panel = pd.DataFrame({"timestamp": [pd.Timestamp("2026-01-01", tz="UTC")]})
    executed: list[int] = []

    def run_candidate(_: Any, __: Any, ___: Any, parameters: dict[str, Any], ____: float) -> Any:
        lookback = int(parameters["lookback"])
        executed.append(lookback)
        if lookback == 20:
            raise PipelineDataQualityError("certification evidence invalid")
        return MockRunResult(sharpe=1.0, run_id=f"run-{lookback}")

    with patch.object(evaluator, "_run", side_effect=run_candidate):
        with pytest.raises(ResearchIntegrityError, match="aborting search"):
            evaluator._select(
                spec, StrategyScope.SINGLE_ASSET, source,
                [{"lookback": 10}, {"lookback": 20}, {"lookback": 30}], 100_000.0,
            )

    assert executed == [10, 20]
    trials = test_db.list_research_trials(family.experiment_family_id)
    assert [trial["parameters"] for trial in trials] == [{"lookback": 10}, {"lookback": 20}]
    assert [trial["status"] for trial in trials] == ["SUCCEEDED", "FAILED"]
