"""Statistically defensible metrics: PSR, DSR, Bootstrap, and Monte Carlo.

References:
    - Bailey, D. H., & López de Prado, M. (2012). The Sharpe Ratio Efficient Frontier.
      Journal of Risk, 15(2), 3-44.
    - Bailey, D. H., & López de Prado, M. (2014). The Deflated Sharpe Ratio:
      Correcting for Selection Bias, Backtest Overfitting and Non-Normality.
      The Journal of Portfolio Management, 40(5), 94-107.
"""

from __future__ import annotations

import json
import math
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
import scipy.special
import scipy.stats

from experiments.trials import canonical_hash

EULER_MASCHERONI = 0.57721566490153286060651209


class EvidenceStatus(str, Enum):
    """Evidence and statistical validity status."""
    VALID = "VALID"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    INVALID_INPUT = "INVALID_INPUT"


class TrialCountSource(str, Enum):
    """Authoritative provenance source of trial multiplicity count for DSR."""
    PHASE2_1_REGISTRY = "PHASE2_1_REGISTRY"
    MANUAL_STATISTICAL_INPUT = "MANUAL_STATISTICAL_INPUT"


class ExpectancyBasis(str, Enum):
    """Basis for bootstrap expectancy confidence intervals."""
    NET_TRADE_PNL = "NET_TRADE_PNL"
    PERIOD_RETURN = "PERIOD_RETURN"


class PSRResult(BaseModel):
    """Result of Probabilistic Sharpe Ratio calculation."""
    psr_value: float | None = None
    sample_sharpe: float | None = None
    annualized_sharpe: float | None = None
    benchmark_sharpe: float = 0.0
    annualized_benchmark_sharpe: float = 0.0
    skewness: float | None = None
    kurtosis: float | None = None
    observations: int = 0
    annualization_factor: float = 252.0
    status: EvidenceStatus = EvidenceStatus.VALID
    reason: str | None = None


class DSRResult(BaseModel):
    """Result of Deflated Sharpe Ratio calculation with trial multiplicity."""
    dsr_value: float | None = None
    expected_max_sharpe: float | None = None
    annualized_expected_max_sharpe: float | None = None
    sample_sharpe: float | None = None
    annualized_sharpe: float | None = None
    variance_trials: float | None = None
    effective_trials: int = 0
    sharpe_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    invalidated_trials: int = 0
    deduplicated_count: int = 0
    total_trials: int = 0
    experiment_family_id: str | None = None
    trial_count_source: TrialCountSource = TrialCountSource.MANUAL_STATISTICAL_INPUT
    trial_ids: list[str] = Field(default_factory=list)
    trial_policy_version: str = "2.6.0"
    trial_policy_hash: str = ""
    status: EvidenceStatus = EvidenceStatus.VALID
    reason: str | None = None


class BootstrapConfidenceIntervals(BaseModel):
    """Bootstrap confidence interval for a single metric."""
    metric_name: str
    point_estimate: float
    median: float
    lower_bound: float
    upper_bound: float
    expectancy_basis: ExpectancyBasis = ExpectancyBasis.PERIOD_RETURN
    confidence_level: float = 0.95
    resamples: int = 1000
    method: str = "MOVING_BLOCK"
    block_size: int | None = 10
    seed: int = 42
    status: EvidenceStatus = EvidenceStatus.VALID
    reason: str | None = None


class MonteCarloRobustnessResult(BaseModel):
    """Monte Carlo resampling and simulation output."""
    simulations: int = 1000
    seed: int = 42
    prob_negative_return: float | None = None
    prob_drawdown_exceeds_threshold: float | None = None
    drawdown_threshold: float = 0.20
    max_drawdown_percentiles: dict[str, float] = Field(default_factory=dict)
    sharpe_percentiles: dict[str, float] = Field(default_factory=dict)
    capital_ruin_probability: float | None = None
    ruin_threshold: float = 0.50
    ruin_level: float | None = None
    ruin_definition: str = "cumulative_equity_breach_below_ruin_level"
    status: EvidenceStatus = EvidenceStatus.VALID
    reason: str | None = None


def _clean_returns(returns: pd.Series | np.ndarray | list[float]) -> np.ndarray:
    """Extract clean 1D float array from various input formats."""
    if isinstance(returns, pd.Series):
        arr = returns.dropna().to_numpy(dtype=float)
    elif isinstance(returns, np.ndarray):
        arr = returns.flatten().astype(float)
        arr = arr[~np.isnan(arr)]
    elif isinstance(returns, (list, tuple)):
        arr = np.array([float(x) for x in returns if x is not None and not math.isnan(float(x))], dtype=float)
    else:
        raise ValueError(f"Unsupported returns type: {type(returns)}")
    return arr


def compute_psr(
    returns: pd.Series | np.ndarray | list[float],
    *,
    benchmark_sharpe: float = 0.0,
    annualization_factor: float = 252.0,
    minimum_observations: int = 30,
) -> PSRResult:
    """Calculate Probabilistic Sharpe Ratio (PSR) for a return series.

    Formula (Bailey & López de Prado, 2012):
        PSR(SR*) = Phi( (SR - SR*) * sqrt(n - 1) / sqrt(1 - gamma_3 * SR + (gamma_4 - 1)/4 * SR^2) )

    Where:
        - SR is the sample non-annualized Sharpe ratio: mean(r) / std(r)
        - SR* is the benchmark non-annualized Sharpe ratio: benchmark_sharpe / sqrt(annualization_factor)
        - gamma_3 is sample skewness: E[(r - mu)^3] / sigma^3
        - gamma_4 is sample kurtosis (non-excess, normal = 3): E[(r - mu)^4] / sigma^4
        - n is the observation count

    Args:
        returns: Return series (daily or bar net returns).
        benchmark_sharpe: Annualized benchmark Sharpe ratio (default 0.0).
        annualization_factor: Frequency multiplier (e.g. 252 for daily, 252*375 for 1m).
        minimum_observations: Minimum required observations to consider evidence valid.

    Returns:
        PSRResult with value in [0, 1] and evidence status.
    """
    if annualization_factor <= 0:
        return PSRResult(
            status=EvidenceStatus.INVALID_INPUT,
            reason=f"annualization_factor must be positive, got {annualization_factor}",
            benchmark_sharpe=0.0,
            annualized_benchmark_sharpe=benchmark_sharpe,
            annualization_factor=annualization_factor,
        )

    ann_factor_sqrt = math.sqrt(annualization_factor)
    sr_star = benchmark_sharpe / ann_factor_sqrt

    try:
        arr = _clean_returns(returns)
    except Exception as exc:
        return PSRResult(
            status=EvidenceStatus.INVALID_INPUT,
            reason=f"Failed to parse returns: {exc}",
            benchmark_sharpe=sr_star,
            annualized_benchmark_sharpe=benchmark_sharpe,
            annualization_factor=annualization_factor,
        )

    n = len(arr)
    if n < minimum_observations:
        return PSRResult(
            observations=n,
            benchmark_sharpe=sr_star,
            annualized_benchmark_sharpe=benchmark_sharpe,
            annualization_factor=annualization_factor,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            reason=f"Observations {n} below minimum threshold {minimum_observations}",
        )

    if not np.all(np.isfinite(arr)):
        return PSRResult(
            observations=n,
            benchmark_sharpe=sr_star,
            annualized_benchmark_sharpe=benchmark_sharpe,
            annualization_factor=annualization_factor,
            status=EvidenceStatus.INVALID_INPUT,
            reason="Returns contain non-finite values (Inf/-Inf)",
        )

    mean_r = float(np.mean(arr))
    var_r = float(np.var(arr, ddof=1))
    std_r = math.sqrt(var_r) if var_r > 0 else 0.0

    if std_r == 0.0 or math.isclose(std_r, 0.0, abs_tol=1e-12):
        return PSRResult(
            observations=n,
            benchmark_sharpe=sr_star,
            annualized_benchmark_sharpe=benchmark_sharpe,
            annualization_factor=annualization_factor,
            status=EvidenceStatus.INVALID_INPUT,
            reason="Zero variance / constant return series",
        )

    sr = mean_r / std_r
    sr_ann = sr * ann_factor_sqrt

    diff = arr - mean_r
    skew = float(np.mean(diff ** 3) / (std_r ** 3))
    kurt = float(np.mean(diff ** 4) / (std_r ** 4))  # Pearson kurtosis, normal = 3

    denom_sq = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * (sr ** 2)
    if denom_sq <= 0:
        return PSRResult(
            sample_sharpe=sr,
            annualized_sharpe=sr_ann,
            benchmark_sharpe=sr_star,
            annualized_benchmark_sharpe=benchmark_sharpe,
            skewness=skew,
            kurtosis=kurt,
            observations=n,
            annualization_factor=annualization_factor,
            status=EvidenceStatus.INVALID_INPUT,
            reason=f"Non-positive denominator variance term {denom_sq:.6f}",
        )

    se = math.sqrt(denom_sq / (n - 1))
    z = (sr - sr_star) / se
    psr_val = float(scipy.stats.norm.cdf(z))

    return PSRResult(
        psr_value=psr_val,
        sample_sharpe=sr,
        annualized_sharpe=sr_ann,
        benchmark_sharpe=sr_star,
        annualized_benchmark_sharpe=benchmark_sharpe,
        skewness=skew,
        kurtosis=kurt,
        observations=n,
        annualization_factor=annualization_factor,
        status=EvidenceStatus.VALID,
    )


def compute_expected_max_sharpe(
    trial_sharpes: list[float] | np.ndarray,
    effective_trials: int | None = None,
    annualization_factor: float = 252.0,
) -> tuple[float, float, float]:
    """Calculate the expected maximum Sharpe ratio under the null hypothesis of no skill.

    Formula (Bailey & López de Prado, 2014):
        SR_0 = sqrt(V) * [ (1 - gamma) * Phi^{-1}(1 - 1/N) + gamma * Phi^{-1}(1 - 1/(N*e)) ]

    Where:
        - gamma is Euler-Mascheroni constant (~0.57721566)
        - N is the effective trial count
        - V is the variance of the non-annualized Sharpe ratios across trials

    Returns:
        tuple of (sr_0_non_ann, sr_0_ann, variance_non_ann)
    """
    clean_sharpes = [float(x) for x in trial_sharpes if x is not None and not math.isnan(float(x))]
    n_trials = effective_trials if (effective_trials is not None and effective_trials > 0) else len(clean_sharpes)

    if n_trials <= 1:
        return 0.0, 0.0, 0.0

    ann_sqrt = math.sqrt(annualization_factor) if annualization_factor > 0 else 1.0

    if len(clean_sharpes) >= 2:
        var_ann = float(np.var(clean_sharpes, ddof=1))
        var_non_ann = var_ann / (ann_sqrt ** 2)
    else:
        var_non_ann = 0.0

    if var_non_ann <= 0.0:
        return 0.0, 0.0, 0.0

    std_non_ann = math.sqrt(var_non_ann)
    q1 = scipy.special.ndtri(1.0 - (1.0 / n_trials))
    q2 = scipy.special.ndtri(1.0 - (1.0 / (n_trials * math.e)))

    factor = (1.0 - EULER_MASCHERONI) * q1 + EULER_MASCHERONI * q2
    sr_0_non_ann = float(std_non_ann * factor)
    sr_0_ann = float(sr_0_non_ann * ann_sqrt)

    return sr_0_non_ann, sr_0_ann, var_non_ann


def compute_dsr_statistic(
    returns: pd.Series | np.ndarray | list[float],
    trial_sharpes: list[float] | np.ndarray,
    *,
    effective_trials: int | None = None,
    annualization_factor: float = 252.0,
    minimum_observations: int = 30,
) -> DSRResult:
    """Pure mathematical Deflated Sharpe Ratio calculation primitive.

    Computes mathematical expected max Sharpe and PSR against expected max Sharpe
    without claiming authoritative Phase 2.1 registry evidence.
    """
    clean_sharpes = [float(x) for x in trial_sharpes if x is not None and not math.isnan(float(x))]
    n_effective = effective_trials if (effective_trials is not None and effective_trials > 0) else len(clean_sharpes)

    if n_effective <= 0 or len(clean_sharpes) < 2:
        return DSRResult(
            effective_trials=n_effective,
            sharpe_count=len(clean_sharpes),
            trial_count_source=TrialCountSource.MANUAL_STATISTICAL_INPUT,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            reason="INSUFFICIENT_SHARPE_OBSERVATIONS_FOR_VARIANCE" if len(clean_sharpes) < 2 else "NO_AUTHORITATIVE_TRIALS",
        )

    sr_0_non_ann, sr_0_ann, var_non_ann = compute_expected_max_sharpe(
        clean_sharpes,
        effective_trials=n_effective,
        annualization_factor=annualization_factor,
    )

    if var_non_ann <= 0.0:
        return DSRResult(
            expected_max_sharpe=0.0,
            annualized_expected_max_sharpe=0.0,
            variance_trials=0.0,
            effective_trials=n_effective,
            sharpe_count=len(clean_sharpes),
            trial_count_source=TrialCountSource.MANUAL_STATISTICAL_INPUT,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            reason="ZERO_TRIAL_SHARPE_VARIANCE",
        )

    psr = compute_psr(
        returns,
        benchmark_sharpe=sr_0_ann,
        annualization_factor=annualization_factor,
        minimum_observations=minimum_observations,
    )

    return DSRResult(
        dsr_value=psr.psr_value,
        expected_max_sharpe=sr_0_non_ann,
        annualized_expected_max_sharpe=sr_0_ann,
        sample_sharpe=psr.sample_sharpe,
        annualized_sharpe=psr.annualized_sharpe,
        variance_trials=var_non_ann,
        effective_trials=n_effective,
        sharpe_count=len(clean_sharpes),
        trial_count_source=TrialCountSource.MANUAL_STATISTICAL_INPUT,
        status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
        reason="MANUAL_STATISTICAL_INPUT_NOT_AUTHORITATIVE",
    )


def resolve_authoritative_dsr(
    db: Any,
    returns: pd.Series | np.ndarray | list[float],
    experiment_family_id: str,
    *,
    annualization_factor: float = 252.0,
    minimum_observations: int = 30,
    trial_policy_version: str = "2.6.0",
    trial_policy_hash: str = "",
) -> DSRResult:
    """Authoritative DSR evaluation strictly resolved from verified database storage.

    This is the ONLY function in the statistical testing architecture that can produce
    an authoritative EvidenceStatus.VALID Deflated Sharpe Ratio (DSR). It directly queries
    the trial registry table (research_trials_log) in DuckDB, audits all trials for the given
    experiment_family_id, deduplicates idempotent replay trials, computes genuine effective
    trial multiplicity (succeeded + failed), extracts genuine Sharpe ratios, and calculates DSR.

    Args:
        db: Storage handle (DuckDBManager or database connection).
        returns: Return series of the selected candidate strategy.
        experiment_family_id: Unique trial registry experiment family identifier.
        annualization_factor: Annualization frequency multiplier (default 252.0).
        minimum_observations: Minimum required return observations (default 30).
        trial_policy_version: Policy version string.
        trial_policy_hash: Policy hash.

    Returns:
        Authoritative DSRResult with full audit trail and evidence status.
    """
    if annualization_factor <= 0.0:
        return DSRResult(
            effective_trials=0,
            sharpe_count=0,
            trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
            experiment_family_id=experiment_family_id,
            status=EvidenceStatus.INVALID_INPUT,
            reason=f"annualization_factor must be positive, got {annualization_factor}",
        )

    if not isinstance(returns, (pd.Series, np.ndarray, list)):
        return DSRResult(
            effective_trials=0,
            sharpe_count=0,
            trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
            experiment_family_id=experiment_family_id,
            status=EvidenceStatus.INVALID_INPUT,
            reason=f"returns must be pd.Series, np.ndarray, or list, got {type(returns).__name__}",
        )

    if db is None:
        return DSRResult(
            effective_trials=0,
            sharpe_count=0,
            trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
            experiment_family_id=experiment_family_id,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            reason="UNVERIFIED_DATABASE_PROVENANCE",
        )

    if not experiment_family_id or not str(experiment_family_id).strip():
        return DSRResult(
            effective_trials=0,
            sharpe_count=0,
            trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            reason="MISSING_AUTHORITATIVE_TRIAL_FAMILY",
        )

    try:
        if hasattr(db, "list_research_trials"):
            trials_log = db.list_research_trials(family_id=experiment_family_id)
        elif hasattr(db, "conn") and hasattr(db.conn, "execute"):
            rows = db.conn.execute(
                "SELECT trial_id, status, trial_json, metrics_json FROM research_trials_log WHERE experiment_family_id = ?",
                [experiment_family_id],
            ).fetchall()
            trials_log = [
                {
                    **(json.loads(str(r[2])) if r[2] else {}),
                    "trial_id": r[0],
                    "status": r[1],
                    "metrics": json.loads(str(r[3])) if r[3] else None,
                }
                for r in rows
            ]
        elif hasattr(db, "execute"):
            rows = db.execute(
                "SELECT trial_id, status, trial_json, metrics_json FROM research_trials_log WHERE experiment_family_id = ?",
                [experiment_family_id],
            ).fetchall()
            trials_log = [
                {
                    **(json.loads(str(r[2])) if r[2] else {}),
                    "trial_id": r[0],
                    "status": r[1],
                    "metrics": json.loads(str(r[3])) if r[3] else None,
                }
                for r in rows
            ]
        else:
            return DSRResult(
                effective_trials=0,
                sharpe_count=0,
                trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
                experiment_family_id=experiment_family_id,
                status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                reason="UNVERIFIED_DATABASE_PROVENANCE",
            )
    except Exception:
        return DSRResult(
            effective_trials=0,
            sharpe_count=0,
            trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
            experiment_family_id=experiment_family_id,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            reason="UNVERIFIED_DATABASE_PROVENANCE",
        )

    if not trials_log:
        return DSRResult(
            effective_trials=0,
            sharpe_count=0,
            trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
            experiment_family_id=experiment_family_id,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            reason="EXPERIMENT_FAMILY_NOT_FOUND_IN_DB",
        )

    registry_sharpes: list[float] = []
    registry_trial_ids: list[str] = []
    succeeded_count = 0
    failed_count = 0
    invalidated_count = 0
    deduplicated_count = 0
    seen_definitions: set[str] = set()

    for tr in trials_log:
        t_id = tr.get("trial_id")
        st = str(tr.get("status", "")).upper()
        if t_id:
            registry_trial_ids.append(str(t_id))

        def_key = canonical_hash({
            "strategy": tr.get("strategy_name"),
            "timeframe": tr.get("timeframe"),
            "parameters": tr.get("parameters"),
            "fold_id": tr.get("fold_id"),
            "train_start": str(tr.get("train_start")),
            "train_end": str(tr.get("train_end")),
            "data_hash": tr.get("data_hash"),
        })

        if def_key in seen_definitions:
            deduplicated_count += 1
            continue
        seen_definitions.add(def_key)

        if st == "SUCCEEDED":
            succeeded_count += 1
            metrics_val = tr.get("metrics") or tr.get("metrics_json") or {}
            if isinstance(metrics_val, str):
                try:
                    metrics_val = json.loads(metrics_val)
                except Exception:
                    metrics_val = {}
            sh_val = metrics_val.get("sharpe") if isinstance(metrics_val, dict) else None
            if sh_val is not None and not math.isnan(float(sh_val)):
                registry_sharpes.append(float(sh_val))
        elif st == "FAILED":
            failed_count += 1
        elif st == "INVALIDATED":
            invalidated_count += 1

    effective_multiplicity = succeeded_count + failed_count
    total_count = len(registry_trial_ids)

    if effective_multiplicity <= 0 or not registry_trial_ids:
        return DSRResult(
            effective_trials=0,
            sharpe_count=0,
            succeeded_count=succeeded_count,
            failed_count=failed_count,
            invalidated_trials=invalidated_count,
            deduplicated_count=deduplicated_count,
            total_trials=total_count,
            experiment_family_id=experiment_family_id,
            trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
            trial_ids=registry_trial_ids,
            trial_policy_version=trial_policy_version,
            trial_policy_hash=trial_policy_hash,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            reason="NO_AUTHORITATIVE_TRIALS",
        )

    if len(registry_sharpes) < 2:
        return DSRResult(
            effective_trials=effective_multiplicity,
            sharpe_count=len(registry_sharpes),
            succeeded_count=succeeded_count,
            failed_count=failed_count,
            invalidated_trials=invalidated_count,
            deduplicated_count=deduplicated_count,
            total_trials=total_count,
            experiment_family_id=experiment_family_id,
            trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
            trial_ids=registry_trial_ids,
            trial_policy_version=trial_policy_version,
            trial_policy_hash=trial_policy_hash,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            reason="INSUFFICIENT_SHARPE_OBSERVATIONS_FOR_VARIANCE",
        )

    sr_0_non_ann, sr_0_ann, var_non_ann = compute_expected_max_sharpe(
        registry_sharpes,
        effective_trials=effective_multiplicity,
        annualization_factor=annualization_factor,
    )

    if var_non_ann <= 0.0:
        return DSRResult(
            expected_max_sharpe=0.0,
            annualized_expected_max_sharpe=0.0,
            variance_trials=0.0,
            effective_trials=effective_multiplicity,
            sharpe_count=len(registry_sharpes),
            succeeded_count=succeeded_count,
            failed_count=failed_count,
            invalidated_trials=invalidated_count,
            deduplicated_count=deduplicated_count,
            total_trials=total_count,
            experiment_family_id=experiment_family_id,
            trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
            trial_ids=registry_trial_ids,
            trial_policy_version=trial_policy_version,
            trial_policy_hash=trial_policy_hash,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            reason="ZERO_TRIAL_SHARPE_VARIANCE",
        )

    psr = compute_psr(
        returns,
        benchmark_sharpe=sr_0_ann,
        annualization_factor=annualization_factor,
        minimum_observations=minimum_observations,
    )

    if psr.status != EvidenceStatus.VALID:
        return DSRResult(
            dsr_value=psr.psr_value,
            expected_max_sharpe=sr_0_non_ann,
            annualized_expected_max_sharpe=sr_0_ann,
            sample_sharpe=psr.sample_sharpe,
            annualized_sharpe=psr.annualized_sharpe,
            variance_trials=var_non_ann,
            effective_trials=effective_multiplicity,
            sharpe_count=len(registry_sharpes),
            succeeded_count=succeeded_count,
            failed_count=failed_count,
            invalidated_trials=invalidated_count,
            deduplicated_count=deduplicated_count,
            total_trials=total_count,
            experiment_family_id=experiment_family_id,
            trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
            trial_ids=registry_trial_ids,
            trial_policy_version=trial_policy_version,
            trial_policy_hash=trial_policy_hash,
            status=psr.status,
            reason=psr.reason,
        )

    return DSRResult(
        dsr_value=psr.psr_value,
        expected_max_sharpe=sr_0_non_ann,
        annualized_expected_max_sharpe=sr_0_ann,
        sample_sharpe=psr.sample_sharpe,
        annualized_sharpe=psr.annualized_sharpe,
        variance_trials=var_non_ann,
        effective_trials=effective_multiplicity,
        sharpe_count=len(registry_sharpes),
        succeeded_count=succeeded_count,
        failed_count=failed_count,
        invalidated_trials=invalidated_count,
        deduplicated_count=deduplicated_count,
        total_trials=total_count,
        experiment_family_id=experiment_family_id,
        trial_count_source=TrialCountSource.PHASE2_1_REGISTRY,
        trial_ids=registry_trial_ids,
        trial_policy_version=trial_policy_version,
        trial_policy_hash=trial_policy_hash,
        status=EvidenceStatus.VALID,
        reason=None,
    )


def compute_dsr(
    returns: pd.Series | np.ndarray | list[float],
    trial_sharpes: list[float] | np.ndarray | None = None,
    *,
    db: Any | None = None,
    trial_count_source: TrialCountSource = TrialCountSource.MANUAL_STATISTICAL_INPUT,
    effective_trials: int | None = None,
    annualization_factor: float = 252.0,
    minimum_observations: int = 30,
    experiment_family_id: str | None = None,
    trial_ids: list[str] | None = None,
    sharpe_count: int | None = None,
    succeeded_count: int = 0,
    failed_count: int = 0,
    invalidated_count: int = 0,
    deduplicated_count: int = 0,
    trial_policy_version: str = "2.6.0",
    trial_policy_hash: str = "",
) -> DSRResult:
    """Calculate Deflated Sharpe Ratio (DSR) correcting for multiple testing.

    Authoritative registry-backed execution requires trial_count_source=PHASE2_1_REGISTRY,
    a valid database handle (db) and experiment_family_id, and routes strictly through
    resolve_authoritative_dsr(). Caller-supplied trial_sharpes or trial counts are disregarded
    to eliminate spoofing.

    Manual statistical input (trial_count_source=MANUAL_STATISTICAL_INPUT) is computed purely
    via compute_dsr_statistic() and fails closed with INSUFFICIENT_EVIDENCE.
    """
    if annualization_factor <= 0.0:
        return DSRResult(
            effective_trials=0,
            sharpe_count=0,
            trial_count_source=trial_count_source,
            experiment_family_id=experiment_family_id,
            trial_ids=trial_ids or [],
            status=EvidenceStatus.INVALID_INPUT,
            reason=f"annualization_factor must be positive, got {annualization_factor}",
        )

    if not isinstance(returns, (pd.Series, np.ndarray, list)):
        return DSRResult(
            effective_trials=0,
            sharpe_count=0,
            trial_count_source=trial_count_source,
            experiment_family_id=experiment_family_id,
            trial_ids=trial_ids or [],
            status=EvidenceStatus.INVALID_INPUT,
            reason=f"returns must be pd.Series, np.ndarray, or list, got {type(returns).__name__}",
        )

    # 1. Authoritative registry branch: routes directly through resolve_authoritative_dsr
    if trial_count_source == TrialCountSource.PHASE2_1_REGISTRY:
        if db is None:
            return DSRResult(
                effective_trials=effective_trials or 0,
                sharpe_count=sharpe_count or 0,
                trial_count_source=trial_count_source,
                experiment_family_id=experiment_family_id,
                trial_ids=trial_ids or [],
                status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                reason="UNVERIFIED_DATABASE_PROVENANCE",
            )
        if not experiment_family_id or not str(experiment_family_id).strip():
            return DSRResult(
                effective_trials=0,
                sharpe_count=0,
                trial_count_source=trial_count_source,
                experiment_family_id=None,
                trial_ids=trial_ids or [],
                status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                reason="MISSING_AUTHORITATIVE_TRIAL_FAMILY",
            )
        return resolve_authoritative_dsr(
            db=db,
            returns=returns,
            experiment_family_id=experiment_family_id,
            annualization_factor=annualization_factor,
            minimum_observations=minimum_observations,
            trial_policy_version=trial_policy_version,
            trial_policy_hash=trial_policy_hash,
        )

    # 2. Manual / unverified branch: pure statistical computation, always fails closed
    clean_sharpes = [float(x) for x in (trial_sharpes or []) if x is not None and not math.isnan(float(x))]
    n_effective = effective_trials if (effective_trials is not None and effective_trials > 0) else len(clean_sharpes)
    math_res = compute_dsr_statistic(
        returns,
        clean_sharpes,
        effective_trials=n_effective,
        annualization_factor=annualization_factor,
        minimum_observations=minimum_observations,
    )
    return DSRResult(
        dsr_value=math_res.dsr_value,
        expected_max_sharpe=math_res.expected_max_sharpe,
        annualized_expected_max_sharpe=math_res.annualized_expected_max_sharpe,
        sample_sharpe=math_res.sample_sharpe,
        annualized_sharpe=math_res.annualized_sharpe,
        variance_trials=math_res.variance_trials,
        effective_trials=n_effective,
        sharpe_count=len(clean_sharpes),
        succeeded_count=succeeded_count,
        failed_count=failed_count,
        invalidated_trials=invalidated_count,
        deduplicated_count=deduplicated_count,
        total_trials=len(trial_ids) if trial_ids else len(clean_sharpes),
        experiment_family_id=experiment_family_id,
        trial_count_source=trial_count_source,
        trial_ids=trial_ids or [],
        trial_policy_version=trial_policy_version,
        trial_policy_hash=trial_policy_hash,
        status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
        reason=math_res.reason or "MANUAL_STATISTICAL_INPUT_NOT_AUTHORITATIVE",
    )


def extract_trade_pnls(fills: pd.DataFrame | None) -> list[float]:
    """Extract net trade PnL observations from fills DataFrame if present."""
    if fills is None or not isinstance(fills, pd.DataFrame) or fills.empty:
        return []
    pnl_col = next((col for col in ["net_pnl", "pnl", "realized_pnl"] if col in fills.columns), None)
    if pnl_col:
        clean_pnls = fills[pnl_col].dropna()
        if not clean_pnls.empty:
            return [float(x) for x in clean_pnls.tolist() if not math.isnan(float(x))]
    if {"symbol", "side", "quantity", "price"}.issubset(fills.columns):
        positions: dict[str, tuple[float, float]] = {}
        pnls: list[float] = []
        ordered = fills.sort_values("timestamp") if "timestamp" in fills.columns else fills
        for _, fill in ordered.iterrows():
            symbol = str(fill["symbol"])
            quantity = float(fill["quantity"])
            price = float(fill["price"])
            fees = float(fill.get("fees", 0.0) or 0.0)
            held, average = positions.get(symbol, (0.0, 0.0))
            if str(fill["side"]).upper() == "BUY":
                new_quantity = held + quantity
                new_average = (held * average + quantity * price + fees) / max(new_quantity, 1e-12)
                positions[symbol] = (new_quantity, new_average)
                continue
            closed = min(quantity, held)
            if closed > 0:
                pnls.append(float((price - average) * closed - fees))
                remaining = held - closed
                if remaining > 0:
                    positions[symbol] = (remaining, average)
                else:
                    positions.pop(symbol, None)
        return pnls
    return []


def compute_bootstrap_confidence_intervals(
    returns: pd.Series | np.ndarray | list[float],
    *,
    fills: pd.DataFrame | None = None,
    confidence_level: float = 0.95,
    n_resamples: int = 1000,
    method: str = "MOVING_BLOCK",
    block_size: int = 10,
    seed: int = 42,
    minimum_observations: int = 20,
    annualization_factor: float = 252.0,
) -> dict[str, BootstrapConfidenceIntervals]:
    """Compute deterministic seeded bootstrap confidence intervals for key metrics.

    Supported metrics:
        - total_return: cumulative return
        - sharpe: annualized Sharpe ratio
        - expectancy: average net return per period (or net trade expectancy if fills supplied)
        - max_drawdown: maximum peak-to-trough decline

    Args:
        returns: Return series (e.g. daily net returns).
        fills: Optional strategy fill records.
        confidence_level: Desired two-sided coverage (e.g. 0.95).
        n_resamples: Number of bootstrap iterations (e.g. 1000).
        method: Resampling method ('IID' or 'MOVING_BLOCK').
        block_size: Window length for moving block bootstrap.
        seed: Random seed for deterministic reproducibility.
        minimum_observations: Minimum return points.
        annualization_factor: Annualization multiplier for Sharpe.

    Returns:
        Dictionary mapping metric names to BootstrapConfidenceIntervals.
    """
    results: dict[str, BootstrapConfidenceIntervals] = {}
    metric_names = ["total_return", "sharpe", "expectancy", "max_drawdown"]

    if not (0.0 < confidence_level < 1.0) or n_resamples <= 0 or block_size <= 0 or annualization_factor <= 0.0:
        for name in metric_names:
            results[name] = BootstrapConfidenceIntervals(
                metric_name=name,
                point_estimate=0.0,
                median=0.0,
                lower_bound=0.0,
                upper_bound=0.0,
                expectancy_basis=ExpectancyBasis.PERIOD_RETURN,
                confidence_level=confidence_level,
                resamples=n_resamples,
                method=method,
                block_size=block_size,
                seed=seed,
                status=EvidenceStatus.INVALID_INPUT,
                reason="Invalid bootstrap parameters (confidence_level, n_resamples, block_size, or annualization_factor)",
            )
        return results

    try:
        arr = _clean_returns(returns)
    except Exception as exc:
        for name in metric_names:
            results[name] = BootstrapConfidenceIntervals(
                metric_name=name,
                point_estimate=0.0,
                median=0.0,
                lower_bound=0.0,
                upper_bound=0.0,
                expectancy_basis=ExpectancyBasis.PERIOD_RETURN,
                confidence_level=confidence_level,
                resamples=n_resamples,
                method=method,
                block_size=block_size,
                seed=seed,
                status=EvidenceStatus.INVALID_INPUT,
                reason=f"Failed to clean returns: {exc}",
            )
        return results

    n = len(arr)
    if n < minimum_observations:
        for name in metric_names:
            results[name] = BootstrapConfidenceIntervals(
                metric_name=name,
                point_estimate=0.0,
                median=0.0,
                lower_bound=0.0,
                upper_bound=0.0,
                expectancy_basis=ExpectancyBasis.PERIOD_RETURN,
                confidence_level=confidence_level,
                resamples=n_resamples,
                method=method,
                block_size=block_size,
                seed=seed,
                status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                reason=f"Observations {n} below minimum threshold {minimum_observations}",
            )
        return results

    rng = np.random.default_rng(seed)
    ann_sqrt = math.sqrt(annualization_factor)

    trade_pnls = extract_trade_pnls(fills)
    use_trade_expectancy = bool(trade_pnls)
    insufficient_trades = use_trade_expectancy and len(trade_pnls) < 5

    def _calc_return_metrics(sample_returns: np.ndarray) -> dict[str, float]:
        cum = np.cumprod(1.0 + sample_returns)
        tot_ret = float(cum[-1] - 1.0) if len(cum) > 0 else 0.0
        mean_s = float(np.mean(sample_returns))
        std_s = float(np.std(sample_returns, ddof=1)) if len(sample_returns) > 1 else 0.0
        sh = float((mean_s / std_s) * ann_sqrt) if std_s > 1e-12 else 0.0
        peaks = np.maximum.accumulate(cum)
        dd = (cum - peaks) / peaks
        max_dd = float(np.min(dd)) if len(dd) > 0 else 0.0
        return {
            "total_return": tot_ret,
            "sharpe": sh,
            "expectancy": mean_s,
            "max_drawdown": max_dd,
        }

    point_estimates = _calc_return_metrics(arr)
    if use_trade_expectancy:
        point_estimates["expectancy"] = float(np.mean(trade_pnls))

    # Generate bootstrap samples
    boot_distributions: dict[str, list[float]] = {name: [] for name in metric_names}
    eff_block = max(1, min(block_size, n))
    trade_pnl_arr = np.array(trade_pnls, dtype=float) if use_trade_expectancy else np.array([])

    for _ in range(n_resamples):
        if method.upper() == "MOVING_BLOCK" and eff_block > 1:
            n_blocks = int(math.ceil(n / eff_block))
            max_start = n - eff_block + 1
            start_indices = rng.integers(0, max_start, size=n_blocks)
            sampled_indices = np.concatenate([np.arange(idx, idx + eff_block) for idx in start_indices])[:n]
            resampled = arr[sampled_indices]
        else:
            indices = rng.integers(0, n, size=n)
            resampled = arr[indices]

        sample_mets = _calc_return_metrics(resampled)
        for name in ["total_return", "sharpe", "max_drawdown"]:
            boot_distributions[name].append(sample_mets[name])

        if use_trade_expectancy and not insufficient_trades:
            # Resample actual trade-PnL observations directly for expectancy distribution
            sampled_trades = rng.choice(trade_pnl_arr, size=len(trade_pnl_arr), replace=True)
            boot_distributions["expectancy"].append(float(np.mean(sampled_trades)))
        else:
            boot_distributions["expectancy"].append(sample_mets["expectancy"])

    alpha = 1.0 - confidence_level
    lower_p = (alpha / 2.0) * 100.0
    upper_p = (1.0 - alpha / 2.0) * 100.0

    for name in metric_names:
        exp_basis = ExpectancyBasis.NET_TRADE_PNL if (name == "expectancy" and use_trade_expectancy) else ExpectancyBasis.PERIOD_RETURN
        if name == "expectancy" and insufficient_trades:
            results[name] = BootstrapConfidenceIntervals(
                metric_name=name,
                point_estimate=point_estimates[name],
                median=point_estimates[name],
                lower_bound=point_estimates[name],
                upper_bound=point_estimates[name],
                expectancy_basis=ExpectancyBasis.NET_TRADE_PNL,
                confidence_level=confidence_level,
                resamples=n_resamples,
                method=method,
                block_size=eff_block if method.upper() == "MOVING_BLOCK" else None,
                seed=seed,
                status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                reason="INSUFFICIENT_TRADE_OBSERVATIONS_FOR_EXPECTANCY",
            )
            continue

        dist = np.array(boot_distributions[name])
        results[name] = BootstrapConfidenceIntervals(
            metric_name=name,
            point_estimate=point_estimates[name],
            median=float(np.percentile(dist, 50.0)),
            lower_bound=float(np.percentile(dist, lower_p)),
            upper_bound=float(np.percentile(dist, upper_p)),
            expectancy_basis=exp_basis,
            confidence_level=confidence_level,
            resamples=n_resamples,
            method=method,
            block_size=eff_block if method.upper() == "MOVING_BLOCK" else None,
            seed=seed,
            status=EvidenceStatus.VALID,
        )

    return results


def compute_monte_carlo_robustness(
    returns: pd.Series | np.ndarray | list[float],
    *,
    fills: pd.DataFrame | None = None,
    n_simulations: int = 1000,
    drawdown_threshold: float = 0.20,
    ruin_threshold: float = 0.50,
    seed: int = 42,
    minimum_observations: int = 20,
    annualization_factor: float = 252.0,
    starting_capital: float = 100_000.0,
) -> MonteCarloRobustnessResult:
    """Perform deterministic Monte Carlo path simulations for risk distributions.

    Capital ruin probability is calculated directly from each simulated cumulative equity path
    where cumulative equity drops below starting_capital * (1.0 - ruin_threshold).

    Args:
        returns: Return series (daily or bar returns).
        fills: Optional fill records.
        n_simulations: Number of synthetic paths to simulate.
        drawdown_threshold: Maximum drawdown risk boundary (e.g. 0.20 for -20%).
        ruin_threshold: Capital ruin drawdown boundary (e.g. 0.50 for -50%).
        seed: Random generator seed.
        minimum_observations: Minimum required observations.
        annualization_factor: Frequency multiplier for Sharpe.
        starting_capital: Starting capital for path simulation.

    Returns:
        MonteCarloRobustnessResult with risk probabilities, ruin level, and percentile distributions.
    """
    if n_simulations <= 0:
        return MonteCarloRobustnessResult(
            simulations=n_simulations,
            seed=seed,
            drawdown_threshold=drawdown_threshold,
            ruin_threshold=ruin_threshold,
            status=EvidenceStatus.INVALID_INPUT,
            reason="n_simulations must be positive",
        )
    if drawdown_threshold <= 0 or ruin_threshold <= 0:
        return MonteCarloRobustnessResult(
            simulations=n_simulations,
            seed=seed,
            drawdown_threshold=drawdown_threshold,
            ruin_threshold=ruin_threshold,
            status=EvidenceStatus.INVALID_INPUT,
            reason="drawdown_threshold and ruin_threshold must be positive",
        )
    try:
        arr = _clean_returns(returns)
    except Exception as exc:
        return MonteCarloRobustnessResult(
            simulations=n_simulations,
            seed=seed,
            drawdown_threshold=drawdown_threshold,
            ruin_threshold=ruin_threshold,
            status=EvidenceStatus.INVALID_INPUT,
            reason=f"Failed to clean returns: {exc}",
        )

    n = len(arr)
    if n < minimum_observations:
        return MonteCarloRobustnessResult(
            simulations=n_simulations,
            seed=seed,
            drawdown_threshold=drawdown_threshold,
            ruin_threshold=ruin_threshold,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            reason=f"Observations {n} below minimum threshold {minimum_observations}",
        )

    rng = np.random.default_rng(seed)
    ann_sqrt = math.sqrt(annualization_factor)

    negative_period_count = 0
    drawdown_breach_count = 0
    ruin_count = 0

    max_drawdowns: list[float] = []
    sharpes: list[float] = []

    norm_dd_thresh = abs(drawdown_threshold)
    norm_ruin_thresh = abs(ruin_threshold)
    ruin_level = float(starting_capital * (1.0 - norm_ruin_thresh))

    for _ in range(n_simulations):
        sampled = rng.choice(arr, size=n, replace=True)
        equity_path = starting_capital * np.cumprod(1.0 + sampled)
        tot_ret = (equity_path[-1] / starting_capital) - 1.0

        if tot_ret < 0.0:
            negative_period_count += 1

        peaks = np.maximum.accumulate(equity_path)
        dds = (equity_path - peaks) / peaks
        worst_dd = abs(float(np.min(dds))) if len(dds) > 0 else 0.0
        max_drawdowns.append(worst_dd)

        if worst_dd >= norm_dd_thresh:
            drawdown_breach_count += 1

        # Capital ruin evaluated directly from cumulative equity path
        min_equity = float(np.min(equity_path))
        if min_equity <= ruin_level:
            ruin_count += 1

        mean_s = float(np.mean(sampled))
        std_s = float(np.std(sampled, ddof=1)) if len(sampled) > 1 else 0.0
        sh = float((mean_s / std_s) * ann_sqrt) if std_s > 1e-12 else 0.0
        sharpes.append(sh)

    dd_arr = np.array(max_drawdowns)
    sh_arr = np.array(sharpes)

    return MonteCarloRobustnessResult(
        simulations=n_simulations,
        seed=seed,
        prob_negative_return=float(negative_period_count / n_simulations),
        prob_drawdown_exceeds_threshold=float(drawdown_breach_count / n_simulations),
        drawdown_threshold=drawdown_threshold,
        max_drawdown_percentiles={
            "p5": float(np.percentile(dd_arr, 5.0)),
            "p50": float(np.percentile(dd_arr, 50.0)),
            "p95": float(np.percentile(dd_arr, 95.0)),
            "p99": float(np.percentile(dd_arr, 99.0)),
        },
        sharpe_percentiles={
            "p5": float(np.percentile(sh_arr, 5.0)),
            "p50": float(np.percentile(sh_arr, 50.0)),
            "p95": float(np.percentile(sh_arr, 95.0)),
        },
        capital_ruin_probability=float(ruin_count / n_simulations),
        ruin_threshold=ruin_threshold,
        ruin_level=ruin_level,
        ruin_definition="cumulative_equity_breach_below_ruin_level",
        status=EvidenceStatus.VALID,
    )
