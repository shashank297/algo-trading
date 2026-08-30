"""Unit and adversarial tests for experiments/statistical_tests.py.

Validates mathematical correctness of PSR, DSR, bootstrap confidence intervals,
and Monte Carlo simulations against analytical formulas and edge cases.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import scipy.stats

from storage.duckdb_manager import DuckDBManager
from storage.migrations.runner import MigrationRunner
from experiments.statistical_tests import (
    EvidenceStatus,
    ExpectancyBasis,
    TrialCountSource,
    compute_bootstrap_confidence_intervals,
    compute_dsr,
    compute_dsr_statistic,
    compute_expected_max_sharpe,
    compute_monte_carlo_robustness,
    compute_psr,
    resolve_authoritative_dsr,
)


def _make_test_db(
    tmp_path: Any,
    family_id: str,
    trial_ids: list[str],
    sharpes: list[float],
    failed_ids: list[str] | None = None,
) -> DuckDBManager:
    """Helper to initialize a DuckDB instance with registered research trial logs."""
    import json
    import uuid

    db_path = str(tmp_path / f"test_dsr_{family_id}_{uuid.uuid4().hex[:6]}.duckdb")
    MigrationRunner(db_path).run_migrations()
    db = DuckDBManager(db_path)
    db.conn.execute(
        f"INSERT INTO experiment_families (experiment_family_id, definition_hash, definition_json, maximum_trials, created_at, started_at) "
        f"VALUES ('{family_id}', 'hash', '{{}}', 500, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )
    for i, (tid, sh) in enumerate(zip(trial_ids, sharpes)):
        t_json = json.dumps({"strategy_name": "test", "parameters": {"p": i}, "fold_id": f"fold-{i}"})
        db.conn.execute(
            "INSERT INTO research_trials_log (trial_id, experiment_family_id, status, trial_json, metrics_json, created_at) "
            "VALUES (?, ?, 'SUCCEEDED', ?, ?, CURRENT_TIMESTAMP)",
            [tid, family_id, t_json, f'{{"sharpe": {sh}}}'],
        )
    if failed_ids:
        for j, fid in enumerate(failed_ids):
            t_json = json.dumps({"strategy_name": "test", "parameters": {"p_failed": j}, "fold_id": f"fold-failed-{j}"})
            db.conn.execute(
                "INSERT INTO research_trials_log (trial_id, experiment_family_id, status, trial_json, metrics_json, created_at) "
                "VALUES (?, ?, 'FAILED', ?, '{}', CURRENT_TIMESTAMP)",
                [fid, family_id, t_json],
            )
    return db


def test_psr_analytical_reference_normal() -> None:
    """Verify PSR matches analytical standard normal CDF under known parameters."""
    rng = np.random.default_rng(12345)
    # Generate 252 daily returns with mean = 0.001 (0.1%/day) and std = 0.01 (1%/day)
    # Annualized Sharpe ~ 0.1 * sqrt(252) ~ 1.587
    raw_returns = rng.normal(loc=0.001, scale=0.01, size=252)
    series = pd.Series(raw_returns)

    # Compute PSR with benchmark 0.0
    psr = compute_psr(series, benchmark_sharpe=0.0, annualization_factor=252.0, minimum_observations=30)
    assert psr.status == EvidenceStatus.VALID
    assert psr.observations == 252
    assert psr.psr_value is not None
    assert 0.0 <= psr.psr_value <= 1.0
    assert psr.sample_sharpe is not None
    assert psr.annualized_sharpe is not None
    assert psr.annualized_sharpe > 0.0
    # For positive Sharpe over 252 days, PSR should be > 0.90
    assert psr.psr_value > 0.90

    # Manual analytical calculation to check exact formula fidelity
    mean_r = float(np.mean(raw_returns))
    std_r = float(np.std(raw_returns, ddof=1))
    sr = mean_r / std_r
    diff = raw_returns - mean_r
    skew = float(np.mean(diff ** 3) / (std_r ** 3))
    kurt = float(np.mean(diff ** 4) / (std_r ** 4))
    denom = math.sqrt((1.0 - skew * sr + ((kurt - 1.0) / 4.0) * (sr ** 2)) / (252 - 1))
    expected_z = sr / denom
    expected_psr = float(scipy.stats.norm.cdf(expected_z))

    assert math.isclose(psr.psr_value, expected_psr, rel_tol=1e-7)


def test_psr_benchmark_threshold_sensitivity() -> None:
    """Higher benchmark Sharpe must strictly reduce PSR."""
    rng = np.random.default_rng(42)
    returns = rng.normal(loc=0.0008, scale=0.012, size=500)

    psr_0 = compute_psr(returns, benchmark_sharpe=0.0)
    psr_1 = compute_psr(returns, benchmark_sharpe=1.0)
    psr_2 = compute_psr(returns, benchmark_sharpe=2.0)

    assert psr_0.status == EvidenceStatus.VALID
    assert psr_1.status == EvidenceStatus.VALID
    assert psr_2.status == EvidenceStatus.VALID
    assert psr_0.psr_value is not None and psr_1.psr_value is not None and psr_2.psr_value is not None
    assert psr_0.psr_value > psr_1.psr_value > psr_2.psr_value


def test_psr_negative_sharpe() -> None:
    """Negative sample Sharpe produces PSR < 0.5 against benchmark 0.0."""
    rng = np.random.default_rng(999)
    returns = rng.normal(loc=-0.001, scale=0.01, size=200)
    psr = compute_psr(returns, benchmark_sharpe=0.0)
    assert psr.status == EvidenceStatus.VALID
    assert psr.psr_value is not None
    assert psr.psr_value < 0.50
    assert psr.psr_value < 0.25


def test_psr_skewed_and_kurtotic_returns() -> None:
    """Non-normal returns with negative skew / fat tails appropriately adjust the denominator."""
    rng = np.random.default_rng(777)
    # Generate skewed Student-t / jump distribution
    normal_part = rng.normal(loc=0.001, scale=0.008, size=300)
    # Add heavy negative jumps
    jumps = rng.choice([0.0, -0.05], size=300, p=[0.95, 0.05])
    returns = normal_part + jumps

    psr = compute_psr(returns, benchmark_sharpe=0.0)
    assert psr.status == EvidenceStatus.VALID
    assert psr.skewness is not None and psr.kurtosis is not None
    assert psr.skewness < 0.0  # Negative skew from jumps
    assert psr.kurtosis > 3.0  # Fat tails / excess kurtosis


def test_psr_adversarial_edge_cases() -> None:
    """Handle insufficient observations, zero variance, NaN/Inf, and bad inputs fail closed."""
    # 1. Low sample count
    short_series = [0.01, -0.01, 0.02]
    psr_short = compute_psr(short_series, minimum_observations=30)
    assert psr_short.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert psr_short.psr_value is None

    # 2. Zero variance / constant series
    constant_series = [0.005] * 50
    psr_const = compute_psr(constant_series)
    assert psr_const.status == EvidenceStatus.INVALID_INPUT
    assert "Zero variance" in str(psr_const.reason)

    # 3. Non-finite values
    inf_series = [0.01] * 40 + [float("inf")]
    psr_inf = compute_psr(inf_series)
    assert psr_inf.status == EvidenceStatus.INVALID_INPUT

    # 4. Negative annualization factor
    psr_neg_ann = compute_psr([0.01] * 50, annualization_factor=-252.0)
    assert psr_neg_ann.status == EvidenceStatus.INVALID_INPUT


def test_dsr_expected_max_sharpe_mathematical_formula() -> None:
    """Verify Bailey & López de Prado (2014) expected maximum Sharpe formula."""
    # With N=1 trial, expected max is 0
    sr0_non_ann, sr0_ann, var = compute_expected_max_sharpe([1.5], effective_trials=1)
    assert sr0_ann == 0.0
    assert sr0_non_ann == 0.0

    # With multiple trials with positive variance:
    # Let 100 trials have standard deviation of annualized Sharpes = 0.5 (variance = 0.25)
    rng = np.random.default_rng(42)
    trials = list(rng.normal(loc=0.0, scale=0.5, size=100))
    sr0_10, sr0_ann_10, _ = compute_expected_max_sharpe(trials, effective_trials=10)
    sr0_50, sr0_ann_50, _ = compute_expected_max_sharpe(trials, effective_trials=50)
    sr0_200, sr0_ann_200, _ = compute_expected_max_sharpe(trials, effective_trials=200)

    # Expected maximum Sharpe must strictly increase as trial count N increases
    assert 0.0 < sr0_ann_10 < sr0_ann_50 < sr0_ann_200


def test_dsr_deflates_as_trials_increase(tmp_path: Any) -> None:
    """DSR value strictly decreases as the number of trials in the experiment family grows."""
    rng = np.random.default_rng(101)
    returns = rng.normal(loc=0.0012, scale=0.01, size=252)

    # Candidate with trial Sharpes across varying registry sizes
    trial_sharpes = list(rng.normal(loc=0.5, scale=0.4, size=100))

    # Mathematical primitive deflates as N grows
    math_5 = compute_dsr_statistic(returns, trial_sharpes[:5], effective_trials=5)
    math_20 = compute_dsr_statistic(returns, trial_sharpes[:20], effective_trials=20)
    math_100 = compute_dsr_statistic(returns, trial_sharpes[:100], effective_trials=100)

    assert math_5.dsr_value is not None and math_20.dsr_value is not None and math_100.dsr_value is not None
    assert math_5.dsr_value > math_20.dsr_value > math_100.dsr_value
    assert math_5.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert math_5.trial_count_source == TrialCountSource.MANUAL_STATISTICAL_INPUT

    # Authoritative storage-backed registry path deflates as N grows and is VALID
    db = _make_test_db(tmp_path, "fam-01", [f"t-{i}" for i in range(100)], trial_sharpes)

    dsr_5 = compute_dsr(
        returns,
        trial_sharpes[:5],
        db=db,
        trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
        effective_trials=5,
        experiment_family_id="fam-01",
        trial_ids=[f"t-{i}" for i in range(5)],
    )
    dsr_20 = compute_dsr(
        returns,
        trial_sharpes[:20],
        db=db,
        trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
        effective_trials=20,
        experiment_family_id="fam-01",
        trial_ids=[f"t-{i}" for i in range(20)],
    )
    dsr_100 = compute_dsr(
        returns,
        trial_sharpes[:100],
        db=db,
        trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
        effective_trials=100,
        experiment_family_id="fam-01",
        trial_ids=[f"t-{i}" for i in range(100)],
    )

    assert dsr_5.status == EvidenceStatus.VALID
    assert dsr_20.status == EvidenceStatus.VALID
    assert dsr_100.status == EvidenceStatus.VALID

    assert dsr_5.dsr_value is not None
    assert dsr_20.dsr_value is not None
    assert dsr_100.dsr_value is not None

    # More trials tried -> higher hurdle SR0 -> lower DSR
    assert dsr_5.dsr_value > dsr_20.dsr_value > dsr_100.dsr_value
    assert dsr_5.effective_trials == 5
    assert dsr_100.effective_trials == 100

    db.close()


def test_dsr_spoofing_prevention_adversarial(tmp_path: Any) -> None:
    """Adversarial test: caller cannot self-declare PHASE2_1_REGISTRY without genuine DB verification."""
    returns = [0.001, -0.0005, 0.002, 0.0015] * 50
    trial_sharpes = [0.8, 1.2, 1.5, 0.9]

    # 1. Manual statistical input without registry provenance fails closed
    dsr_spoofed = compute_dsr(
        returns,
        trial_sharpes,
        effective_trials=100,
        experiment_family_id="made-up-family",
        trial_ids=["fake-trial-1", "fake-trial-2"],
    )
    assert dsr_spoofed.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert dsr_spoofed.reason == "MANUAL_STATISTICAL_INPUT_NOT_AUTHORITATIVE"
    assert dsr_spoofed.trial_count_source == TrialCountSource.MANUAL_STATISTICAL_INPUT

    # 2. Self-declared PHASE2_1_REGISTRY without database handle fails closed
    dsr_no_db = compute_dsr(
        returns,
        trial_sharpes,
        trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
        effective_trials=4,
        experiment_family_id="fam-01",
        trial_ids=["t-1", "t-2", "t-3", "t-4"],
    )
    assert dsr_no_db.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert dsr_no_db.reason == "UNVERIFIED_DATABASE_PROVENANCE"

    # 3. Non-existent experiment family in DB fails closed
    db = _make_test_db(tmp_path, "fam-real", ["t-1", "t-2", "t-3", "t-4"], trial_sharpes)
    dsr_fake_fam = compute_dsr(
        returns,
        trial_sharpes,
        db=db,
        trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
        effective_trials=4,
        experiment_family_id="fam-nonexistent",
        trial_ids=["t-1", "t-2", "t-3", "t-4"],
    )
    assert dsr_fake_fam.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert dsr_fake_fam.reason == "EXPERIMENT_FAMILY_NOT_FOUND_IN_DB"

    # 4. Fabricated trial IDs not present in DB fail closed
    dsr_fake_ids = compute_dsr(
        returns,
        trial_sharpes,
        db=db,
        trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
        effective_trials=4,
        experiment_family_id="fam-real",
        trial_ids=["fake-1", "fake-2"],
    )
    assert dsr_fake_ids.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert dsr_fake_ids.reason == "TRIAL_IDS_NOT_FOUND_IN_DB"

    # 5. Genuine authoritative trial family in DB passes with VALID status
    dsr_auth = compute_dsr(
        returns,
        trial_sharpes,
        db=db,
        trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
        effective_trials=4,
        experiment_family_id="fam-real",
        trial_ids=["t-1", "t-2", "t-3", "t-4"],
    )
    assert dsr_auth.status == EvidenceStatus.VALID
    assert dsr_auth.trial_count_source == TrialCountSource.PHASE2_1_REGISTRY

    # 6. resolve_authoritative_dsr also resolves and passes with VALID status
    dsr_resolved = resolve_authoritative_dsr(db, returns, "fam-real")
    assert dsr_resolved.status == EvidenceStatus.VALID
    assert dsr_resolved.trial_count_source == TrialCountSource.PHASE2_1_REGISTRY
    assert dsr_resolved.effective_trials == 4
    assert dsr_resolved.sharpe_count == 4

    db.close()


def test_dsr_fail_closed_missing_experiment_family(tmp_path: Any) -> None:
    """DSR must fail closed with INSUFFICIENT_EVIDENCE if experiment_family_id is missing."""
    returns = [0.001] * 100
    trial_sharpes = [1.0, 1.2, 0.8]
    db = _make_test_db(tmp_path, "fam-miss", ["t-1", "t-2", "t-3"], trial_sharpes)

    dsr_missing_fam = compute_dsr(
        returns,
        trial_sharpes,
        db=db,
        trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
        trial_ids=["t-1"],
        experiment_family_id=None,
    )
    assert dsr_missing_fam.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert dsr_missing_fam.reason == "MISSING_AUTHORITATIVE_TRIAL_FAMILY"
    assert dsr_missing_fam.dsr_value is None

    dsr_empty_fam = compute_dsr(
        returns,
        trial_sharpes,
        db=db,
        trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
        trial_ids=["t-1"],
        experiment_family_id="   ",
    )
    assert dsr_empty_fam.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert dsr_empty_fam.reason == "MISSING_AUTHORITATIVE_TRIAL_FAMILY"

    db.close()


def test_dsr_fail_closed_insufficient_sharpe_observations(tmp_path: Any) -> None:
    """DSR requires at least 2 valid Sharpe observations to estimate variance."""
    returns = [0.001] * 100
    db = _make_test_db(tmp_path, "fam-single", ["t-1"], [1.5])

    # Single trial Sharpe observation cannot compute variance
    dsr_single = compute_dsr(
        returns,
        [1.5],
        db=db,
        trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
        effective_trials=10,
        experiment_family_id="fam-single",
        trial_ids=["t-1"],
    )
    assert dsr_single.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert dsr_single.reason == "INSUFFICIENT_SHARPE_OBSERVATIONS_FOR_VARIANCE"

    db.close()


def test_dsr_trial_multiplicity_accounting(tmp_path: Any) -> None:
    """Failed genuine trials increase effective multiplicity N without contributing a Sharpe ratio."""
    rng = np.random.default_rng(2026)
    returns = rng.normal(loc=0.0015, scale=0.01, size=252)

    succeeded_sharpes = [0.8, 1.2, 1.5, 0.9]  # 4 succeeded trials
    succeeded_ids = [f"t-succ-{i}" for i in range(4)]
    failed_ids = [f"t-fail-{i}" for i in range(16)]  # 16 failed trials -> effective N = 20

    db = _make_test_db(tmp_path, "fam-multiplicity", succeeded_ids, succeeded_sharpes, failed_ids=failed_ids)

    dsr_with_failed = compute_dsr(
        returns,
        succeeded_sharpes,
        db=db,
        trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
        succeeded_count=4,
        failed_count=16,
        effective_trials=20,
        experiment_family_id="fam-multiplicity",
        trial_ids=succeeded_ids + failed_ids,
    )
    assert dsr_with_failed.status == EvidenceStatus.VALID
    assert dsr_with_failed.effective_trials == 20
    assert dsr_with_failed.sharpe_count == 4
    assert dsr_with_failed.succeeded_count == 4
    assert dsr_with_failed.failed_count == 16

    # Test resolution through resolve_authoritative_dsr
    dsr_resolved = resolve_authoritative_dsr(db, returns, "fam-multiplicity")
    assert dsr_resolved.status == EvidenceStatus.VALID
    assert dsr_resolved.effective_trials == 20
    assert dsr_resolved.sharpe_count == 4
    assert dsr_resolved.succeeded_count == 4
    assert dsr_resolved.failed_count == 16

    db.close()


def test_deterministic_bootstrap_reproducibility_and_intervals() -> None:
    """Bootstrap confidence intervals are deterministic given seed and bound point estimates."""
    rng = np.random.default_rng(2026)
    returns = rng.normal(loc=0.0005, scale=0.015, size=150)

    # 1. Run twice with identical seed -> identical output
    ci_1 = compute_bootstrap_confidence_intervals(returns, confidence_level=0.95, n_resamples=500, seed=42)
    ci_2 = compute_bootstrap_confidence_intervals(returns, confidence_level=0.95, n_resamples=500, seed=42)

    for metric in ["total_return", "sharpe", "expectancy", "max_drawdown"]:
        assert ci_1[metric].status == EvidenceStatus.VALID
        assert ci_1[metric].point_estimate == ci_2[metric].point_estimate
        assert ci_1[metric].median == ci_2[metric].median
        assert ci_1[metric].lower_bound == ci_2[metric].lower_bound
        assert ci_1[metric].upper_bound == ci_2[metric].upper_bound
        # Lower bound must be <= upper bound
        assert ci_1[metric].lower_bound <= ci_1[metric].upper_bound
        assert ci_1[metric].expectancy_basis == ExpectancyBasis.PERIOD_RETURN

    # 2. Run with different seed -> may produce slightly different samples but valid
    ci_diff = compute_bootstrap_confidence_intervals(returns, confidence_level=0.95, n_resamples=500, seed=999)
    assert ci_diff["sharpe"].status == EvidenceStatus.VALID
    assert ci_diff["sharpe"].lower_bound <= ci_diff["sharpe"].upper_bound


def test_bootstrap_trade_expectancy_units_and_independence() -> None:
    """Verify that trade expectancy resamples trade PnLs directly in monetary units without mixing period returns."""
    returns = np.array([0.001, 0.002, -0.001, 0.0015] * 25)
    
    # 10 trade PnLs with mean = 500.0 (in ₹)
    trade_pnls = [200.0, 800.0, -100.0, 400.0, 1200.0, -300.0, 600.0, 500.0, 700.0, 1000.0]
    fills_df = pd.DataFrame({
        "net_pnl": trade_pnls,
        "quantity": [10.0] * 10,
        "price": [100.0] * 10,
    })

    ci = compute_bootstrap_confidence_intervals(returns, fills=fills_df, confidence_level=0.95, n_resamples=500, seed=42)
    exp_ci = ci["expectancy"]

    assert exp_ci.status == EvidenceStatus.VALID
    assert exp_ci.expectancy_basis == ExpectancyBasis.NET_TRADE_PNL
    assert math.isclose(exp_ci.point_estimate, 500.0, rel_tol=1e-6)
    # Median and CI bounds must all be in trade PnL units (hundreds of ₹), NOT small percentage decimals (0.001)
    assert exp_ci.median > 100.0
    assert exp_ci.lower_bound > -500.0
    assert exp_ci.upper_bound > 500.0
    assert exp_ci.lower_bound <= exp_ci.median <= exp_ci.upper_bound

    # Independence test: Mutating returns while keeping fills constant does NOT change trade expectancy CI
    perturbed_returns = returns * 10.0
    ci_perturbed_returns = compute_bootstrap_confidence_intervals(perturbed_returns, fills=fills_df, confidence_level=0.95, n_resamples=500, seed=42)
    assert math.isclose(ci_perturbed_returns["expectancy"].point_estimate, exp_ci.point_estimate)
    assert math.isclose(ci_perturbed_returns["expectancy"].lower_bound, exp_ci.lower_bound)
    assert math.isclose(ci_perturbed_returns["expectancy"].upper_bound, exp_ci.upper_bound)

    # Mutating fills changes trade expectancy CI
    fills_doubled = pd.DataFrame({"net_pnl": [p * 2.0 for p in trade_pnls]})
    ci_doubled = compute_bootstrap_confidence_intervals(returns, fills=fills_doubled, confidence_level=0.95, n_resamples=500, seed=42)
    assert math.isclose(ci_doubled["expectancy"].point_estimate, 1000.0, rel_tol=1e-6)
    assert ci_doubled["expectancy"].lower_bound > exp_ci.lower_bound

    # Fills with fewer than 5 trades fail closed for expectancy with INSUFFICIENT_EVIDENCE
    fills_few = pd.DataFrame({"net_pnl": [100.0, 200.0]})
    ci_few = compute_bootstrap_confidence_intervals(returns, fills=fills_few, minimum_observations=20)
    assert ci_few["expectancy"].status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert ci_few["expectancy"].reason == "INSUFFICIENT_TRADE_OBSERVATIONS_FOR_EXPECTANCY"


def test_deterministic_bootstrap_moving_block_vs_iid() -> None:
    """Moving block bootstrap runs cleanly and respects block size."""
    returns = np.random.normal(loc=0.001, scale=0.01, size=100)
    ci_block = compute_bootstrap_confidence_intervals(returns, method="MOVING_BLOCK", block_size=10, seed=123)
    ci_iid = compute_bootstrap_confidence_intervals(returns, method="IID", seed=123)

    assert ci_block["sharpe"].status == EvidenceStatus.VALID
    assert ci_iid["sharpe"].status == EvidenceStatus.VALID
    assert ci_block["sharpe"].block_size == 10
    assert ci_iid["sharpe"].block_size is None


def test_bootstrap_insufficient_data() -> None:
    """Bootstrap fails safely on insufficient data."""
    ci = compute_bootstrap_confidence_intervals([0.01, -0.01], minimum_observations=20)
    assert ci["sharpe"].status == EvidenceStatus.INSUFFICIENT_EVIDENCE


def test_monte_carlo_simulation_distributions_and_ruin() -> None:
    """Monte Carlo generates valid risk distributions, threshold breaches, and ruin probabilities."""
    rng = np.random.default_rng(888)
    pos_returns = rng.normal(loc=0.002, scale=0.008, size=200)

    mc_pos = compute_monte_carlo_robustness(
        pos_returns,
        n_simulations=500,
        drawdown_threshold=0.15,
        ruin_threshold=0.30,
        seed=42,
        starting_capital=100_000.0,
    )
    assert mc_pos.status == EvidenceStatus.VALID
    assert mc_pos.prob_negative_return is not None
    assert 0.0 <= mc_pos.prob_negative_return <= 0.10
    assert mc_pos.prob_drawdown_exceeds_threshold is not None
    assert mc_pos.capital_ruin_probability is not None
    assert mc_pos.ruin_level == 70_000.0
    assert "p50" in mc_pos.max_drawdown_percentiles
    assert "p95" in mc_pos.max_drawdown_percentiles
    assert mc_pos.max_drawdown_percentiles["p5"] <= mc_pos.max_drawdown_percentiles["p95"]

    # Determinism check: identical seed produces identical result
    mc_pos_replay = compute_monte_carlo_robustness(
        pos_returns,
        n_simulations=500,
        drawdown_threshold=0.15,
        ruin_threshold=0.30,
        seed=42,
        starting_capital=100_000.0,
    )
    assert mc_pos.prob_negative_return == mc_pos_replay.prob_negative_return
    assert mc_pos.max_drawdown_percentiles == mc_pos_replay.max_drawdown_percentiles

    # High-risk negative drift series -> high ruin probability
    neg_returns = rng.normal(loc=-0.01, scale=0.03, size=200)
    mc_neg = compute_monte_carlo_robustness(
        neg_returns,
        n_simulations=500,
        drawdown_threshold=0.20,
        ruin_threshold=0.50,
        seed=42,
        starting_capital=100_000.0,
    )
    assert mc_neg.prob_negative_return is not None
    assert mc_neg.prob_negative_return > 0.90
    assert mc_neg.capital_ruin_probability is not None
    assert mc_neg.capital_ruin_probability > 0.50
    assert mc_neg.ruin_level == 50_000.0


def test_statistical_tests_edge_cases_and_error_branches() -> None:
    """Cover all remaining error branches and fallback conditions."""
    # 1. compute_expected_max_sharpe with empty trial list
    sr0_non, sr0_ann, var = compute_expected_max_sharpe([], effective_trials=0)
    assert sr0_non == 0.0 and sr0_ann == 0.0 and var == 0.0

    # 2. compute_psr with empty returns and zero observations
    psr_empty = compute_psr(pd.Series([], dtype=float))
    assert psr_empty.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert psr_empty.reason is not None and "below minimum threshold" in psr_empty.reason

    # 3. compute_dsr with invalid input exceptions
    from typing import Any, cast
    dsr_invalid = compute_dsr(
        cast(Any, "invalid_type"),
        [1.0, 1.2],
        trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
        experiment_family_id="fam-01",
        trial_ids=["t-1", "t-2"],
    )
    assert dsr_invalid.status == EvidenceStatus.INVALID_INPUT

    # 4. compute_dsr with invalid annualization factor
    dsr_neg_ann = compute_dsr(
        [0.01, 0.02, 0.03] * 20,
        [1.0, 1.2],
        trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
        annualization_factor=-1.0,
        experiment_family_id="fam-01",
        trial_ids=["t-1", "t-2"],
    )
    assert dsr_neg_ann.status == EvidenceStatus.INVALID_INPUT

    # 5. compute_dsr with identical sharpe observations (variance = 0) fails closed
    dsr_zero_var = compute_dsr(
        [0.01, 0.02, 0.03] * 20,
        [1.0, 1.0],
    )
    assert dsr_zero_var.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert dsr_zero_var.reason == "ZERO_TRIAL_SHARPE_VARIANCE"

    # 6. compute_bootstrap_confidence_intervals with zero variance returns and with fills
    ci_zero_var = compute_bootstrap_confidence_intervals([0.01] * 50)
    assert ci_zero_var["sharpe"].status == EvidenceStatus.VALID

    dummy_fills = pd.DataFrame({"cost": [10.0, 20.0], "fill_price": [100.0, 105.0]})
    ci_fills = compute_bootstrap_confidence_intervals([0.01, -0.005] * 25, fills=dummy_fills)
    assert ci_fills["expectancy"].status == EvidenceStatus.VALID

    # 7. compute_bootstrap_confidence_intervals with invalid inputs
    ci_invalid = compute_bootstrap_confidence_intervals(cast(Any, "not_a_series"))
    assert ci_invalid["sharpe"].status == EvidenceStatus.INVALID_INPUT

    # 8. compute_monte_carlo_robustness with invalid simulations and thresholds
    mc_invalid_sim = compute_monte_carlo_robustness([0.01] * 50, n_simulations=0)
    assert mc_invalid_sim.status == EvidenceStatus.INVALID_INPUT

    mc_invalid_thresh = compute_monte_carlo_robustness([0.01] * 50, drawdown_threshold=-0.1)
    assert mc_invalid_thresh.status == EvidenceStatus.INVALID_INPUT

    mc_invalid_ruin = compute_monte_carlo_robustness([0.01] * 50, ruin_threshold=-0.5)
    assert mc_invalid_ruin.status == EvidenceStatus.INVALID_INPUT

    mc_invalid_cap = compute_monte_carlo_robustness([0.01] * 50, starting_capital=100_000.0)
    assert mc_invalid_cap.status == EvidenceStatus.VALID

    mc_invalid_input = compute_monte_carlo_robustness(cast(Any, "bad_input"))
    assert mc_invalid_input.status == EvidenceStatus.INVALID_INPUT

    mc_low_obs = compute_monte_carlo_robustness([0.01, -0.01], minimum_observations=30)
    assert mc_low_obs.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
