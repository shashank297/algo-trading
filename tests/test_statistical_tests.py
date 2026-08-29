"""Unit and adversarial tests for experiments/statistical_tests.py.

Validates mathematical correctness of PSR, DSR, bootstrap confidence intervals,
and Monte Carlo simulations against analytical formulas and edge cases.
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
import scipy.stats

from experiments.statistical_tests import (
    EvidenceStatus,
    compute_bootstrap_confidence_intervals,
    compute_dsr,
    compute_expected_max_sharpe,
    compute_monte_carlo_robustness,
    compute_psr,
)


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


def test_dsr_deflates_as_trials_increase() -> None:
    """DSR value strictly decreases as the number of trials in the experiment family grows."""
    rng = np.random.default_rng(101)
    returns = rng.normal(loc=0.0012, scale=0.01, size=252)

    # Candidate with trial Sharpes across varying registry sizes
    trial_sharpes = list(rng.normal(loc=0.5, scale=0.4, size=100))

    dsr_5 = compute_dsr(returns, trial_sharpes[:5], effective_trials=5, experiment_family_id="fam-01")
    dsr_20 = compute_dsr(returns, trial_sharpes[:20], effective_trials=20, experiment_family_id="fam-01")
    dsr_100 = compute_dsr(returns, trial_sharpes[:100], effective_trials=100, experiment_family_id="fam-01")

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


def test_dsr_fail_closed_missing_experiment_family() -> None:
    """DSR must fail closed with INSUFFICIENT_EVIDENCE if experiment_family_id is missing."""
    returns = [0.001] * 100
    trial_sharpes = [1.0, 1.2, 0.8]

    dsr_missing_fam = compute_dsr(returns, trial_sharpes, experiment_family_id=None)
    assert dsr_missing_fam.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert dsr_missing_fam.reason == "MISSING_AUTHORITATIVE_TRIAL_FAMILY"
    assert dsr_missing_fam.dsr_value is None

    dsr_empty_fam = compute_dsr(returns, trial_sharpes, experiment_family_id="   ")
    assert dsr_empty_fam.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert dsr_empty_fam.reason == "MISSING_AUTHORITATIVE_TRIAL_FAMILY"


def test_dsr_fail_closed_insufficient_sharpe_observations() -> None:
    """DSR requires at least 2 valid Sharpe observations to estimate variance."""
    returns = [0.001] * 100

    # Single trial Sharpe observation cannot compute variance
    dsr_single = compute_dsr(returns, [1.5], effective_trials=10, experiment_family_id="fam-01")
    assert dsr_single.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert dsr_single.reason == "INSUFFICIENT_SHARPE_OBSERVATIONS_FOR_VARIANCE"


def test_dsr_trial_multiplicity_accounting() -> None:
    """Failed genuine trials increase effective multiplicity N without contributing a Sharpe ratio."""
    rng = np.random.default_rng(2026)
    returns = rng.normal(loc=0.0015, scale=0.01, size=252)

    succeeded_sharpes = [0.8, 1.2, 1.5, 0.9]  # 4 succeeded trials
    failed_count = 16  # 16 failed trials -> effective N = 20

    dsr_with_failed = compute_dsr(
        returns,
        succeeded_sharpes,
        succeeded_count=4,
        failed_count=failed_count,
        effective_trials=20,
        experiment_family_id="fam-multiplicity",
    )
    assert dsr_with_failed.status == EvidenceStatus.VALID
    assert dsr_with_failed.effective_trials == 20
    assert dsr_with_failed.sharpe_count == 4
    assert dsr_with_failed.succeeded_count == 4
    assert dsr_with_failed.failed_count == 16


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

    # 2. Run with different seed -> may produce slightly different samples but valid
    ci_diff = compute_bootstrap_confidence_intervals(returns, confidence_level=0.95, n_resamples=500, seed=999)
    assert ci_diff["sharpe"].status == EvidenceStatus.VALID
    assert ci_diff["sharpe"].lower_bound <= ci_diff["sharpe"].upper_bound


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
    # Profitable return series with low volatility
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
    assert 0.0 <= mc_pos.prob_negative_return <= 0.10  # Highly profitable, rarely negative
    assert mc_pos.prob_drawdown_exceeds_threshold is not None
    assert mc_pos.capital_ruin_probability is not None
    assert mc_pos.ruin_level == 70_000.0  # 100_000 * (1 - 0.30)
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
    dsr_invalid = compute_dsr(cast(Any, "invalid_type"), [1.0, 1.2], experiment_family_id="fam-01")
    assert dsr_invalid.status == EvidenceStatus.INVALID_INPUT

    # 4. compute_dsr with invalid annualization factor
    dsr_neg_ann = compute_dsr([0.01, 0.02, 0.03] * 20, [1.0, 1.2], annualization_factor=-1.0, experiment_family_id="fam-01")
    assert dsr_neg_ann.status == EvidenceStatus.INVALID_INPUT

    # 5. compute_dsr with identical sharpe observations (variance = 0) fails closed
    dsr_zero_var = compute_dsr([0.01, 0.02, 0.03] * 20, [1.0, 1.0], experiment_family_id="fam-01")
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
