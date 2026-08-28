# Phase 2.6 Data Model: Statistically Defensible Research Framework

## Entities & Enums

### 1. `EvidenceStatus` (Enum)
- `VALID`: Valid calculation with sufficient evidence and satisfying all domain constraints.
- `INSUFFICIENT_EVIDENCE`: Sample size below minimum threshold or observations insufficient.
- `INVALID_INPUT`: Inputs contain NaN, Inf, non-positive variance, or violate parameter constraints.

### 2. `PSRResult` (Pydantic Model)
- `psr_value`: `float | None` — Probabilistic Sharpe Ratio in $[0, 1]$.
- `sample_sharpe`: `float | None` — Sample non-annualized Sharpe ratio $\widehat{SR}$.
- `annualized_sharpe`: `float | None` — Annualized sample Sharpe ratio $\widehat{SR} \cdot \sqrt{A}$.
- `benchmark_sharpe`: `float` — Benchmark non-annualized Sharpe ratio $SR^*$.
- `annualized_benchmark_sharpe`: `float` — Benchmark annualized Sharpe ratio.
- `skewness`: `float | None` — Sample skewness $\gamma_3$.
- `kurtosis`: `float | None` — Sample kurtosis $\gamma_4$ (normal = 3).
- `observations`: `int` — Number of return observations $n$.
- `annualization_factor`: `float` — Annualization factor $A$ (e.g. 252 for daily).
- `status`: `EvidenceStatus` — Evaluation status.
- `reason`: `str | None` — Descriptive status explanation.

### 3. `DSRResult` (Pydantic Model)
- `dsr_value`: `float | None` — Deflated Sharpe Ratio in $[0, 1]$.
- `expected_max_sharpe`: `float | None` — $SR_0$ expected maximum Sharpe under null hypothesis.
- `sample_sharpe`: `float | None` — Sample non-annualized Sharpe ratio.
- `annualized_sharpe`: `float | None` — Annualized Sharpe ratio.
- `variance_trials`: `float | None` — Estimated variance of Sharpe ratios across trials $V(\{SR_k\})$.
- `effective_trials`: `int` — Effective independent trial count $N$ from authoritative registry.
- `total_trials`: `int` — Total trial count in experiment family query scope.
- `invalidated_trials`: `int` — Count of invalidated trials.
- `experiment_family_id`: `str | None` — Authoritative trial registry experiment family ID.
- `trial_ids`: `list[str]` — List of trial IDs evaluated.
- `status`: `EvidenceStatus` — Evaluation status.
- `reason`: `str | None` — Status explanation.

### 4. `BootstrapConfidenceIntervals` (Pydantic Model)
- `metric_name`: `str` — Metric identifier (e.g. `total_return`, `sharpe`, `expectancy`, `max_drawdown`).
- `lower_bound`: `float` — Lower percentile bound (e.g. 2.5th for 95% CI).
- `upper_bound`: `float` — Upper percentile bound (e.g. 97.5th for 95% CI).
- `median`: `float` — Resampled median value.
- `point_estimate`: `float` — Original point estimate.
- `confidence_level`: `float` — Configured confidence level (e.g. 0.95).
- `resamples`: `int` — Number of bootstrap resamples.
- `method`: `str` — `IID` or `MOVING_BLOCK`.
- `block_size`: `int | None` — Block size if block bootstrap.
- `seed`: `int` — Seed used for deterministic reproducibility.
- `status`: `EvidenceStatus` — Status.

### 5. `MonteCarloRobustnessResult` (Pydantic Model)
- `simulations`: `int` — Number of simulation paths (e.g. 1000).
- `seed`: `int` — Simulation seed.
- `prob_negative_return`: `float` — $P(\text{Return} < 0)$.
- `prob_drawdown_exceeds_threshold`: `float` — $P(\text{MaxDD} > \text{threshold})$.
- `drawdown_threshold`: `float` — Drawdown threshold (e.g. 0.20 for 20%).
- `max_drawdown_percentiles`: `dict[str, float]` — `{"p5": ..., "p50": ..., "p95": ..., "p99": ...}`.
- `sharpe_percentiles`: `dict[str, float]` — `{"p5": ..., "p50": ..., "p95": ...}`.
- `capital_ruin_probability`: `float` — Estimated ruin probability.
- `ruin_threshold`: `float` — Ruin equity/drawdown threshold.
- `status`: `EvidenceStatus` — Status.

### 6. `ParameterRobustnessCandidate` (Pydantic Model)
- `parameters`: `dict[str, Any]` — Parameter values.
- `parameter_hash`: `str` — SHA-256 parameter hash.
- `train_score`: `float` — Raw performance score on TRAIN.
- `val_score`: `float | None` — Raw performance score on VALIDATION.
- `neighbor_parameters`: `list[dict[str, Any]]` — Neighboring candidates in grid.
- `neighbor_scores`: `list[float]` — Scores of neighboring candidates.
- `neighbor_mean`: `float` — Mean score across neighbors.
- `neighbor_std`: `float` — Score standard deviation across neighbors.
- `plateau_score`: `float` — Ratio of neighbor mean to center / fraction meeting threshold.
- `sensitivity_score`: `float` — Drop-off / sensitivity metric.
- `rank_stability`: `float` — Cross-fold rank stability score.
- `aggregate_robustness_score`: `float` — Composite robustness score used for selection.
- `selected`: `bool` — Whether candidate is selected by policy.
- `selection_reason`: `str | None` — Rationale for selection.

### 7. `NestedFoldEvidence` (Pydantic Model)
- `fold_id`: `str` — Fold identifier (e.g. `nfold-001`).
- `train_start`: `datetime` — Train window start.
- `train_end`: `datetime` — Train window end.
- `val_start`: `datetime` — Validation window start.
- `val_end`: `datetime` — Validation window end.
- `test_start`: `datetime` — Final OOS test window start.
- `test_end`: `datetime` — Final OOS test window end.
- `purge_window`: `int` — Purge bar window.
- `embargo_window`: `int` — Embargo bar window.
- `train_data_hash`: `str` — SHA-256 data hash of TRAIN slice.
- `val_data_hash`: `str` — SHA-256 data hash of VALIDATION slice.
- `test_data_hash`: `str` — SHA-256 data hash of FINAL OOS slice.
- `frame_certification_id`: `str | None` — Frame certification ID.
- `selected_parameters`: `dict[str, Any]` — Parameters selected on TRAIN/VAL.
- `selected_trial_id`: `str | None` — Trial registry ID.
- `train_metrics`: `dict[str, float]` — Metrics on TRAIN.
- `val_metrics`: `dict[str, float]` — Metrics on VALIDATION.
- `final_oos_metrics`: `dict[str, float]` — Metrics on FINAL OOS TEST.
- `evidence_hash`: `str` — Deterministic fold evidence hash.

### 8. `CostStressResult` (Pydantic Model)
- `multiplier`: `float` — Cost multiplier ($1.0, 1.5, 2.0, 3.0$).
- `slippage_bps_override`: `float | None` — Stressed slippage in bps.
- `liquidity_stress_factor`: `float | None` — Liquidity penalty factor.
- `metrics`: `dict[str, float]` — Recomputed net performance metrics (Sharpe, CAGR, MaxDD, Total Return, Net PnL).
- `cost_schedule_summary`: `dict[str, Any]` — Summary of cost assumptions applied.

### 9. `ExecutionStressResult` (Pydantic Model)
- `scenario_name`: `str` — Name of execution scenario (e.g. `overnight_gap_stress`, `stop_slippage_stress`, `execution_delay_1bar`, `missed_fills_5pct`).
- `perturbation_params`: `dict[str, Any]` — Configured perturbation parameters.
- `metrics`: `dict[str, float]` — Stressed net metrics.
- `seed`: `int | None` — Resampling/perturbation seed.

### 10. `RobustnessBundle` (Pydantic Model)
- `robustness_id`: `str` — Deterministic SHA-256 identity.
- `run_id`: `str` — Associated strategy run ID.
- `experiment_family_id`: `str | None` — Experiment family ID if registered.
- `strategy_name`: `str` — Strategy name.
- `strategy_version`: `str` — Strategy version.
- `selected_trial_id`: `str | None` — Selected trial ID.
- `evidence_status`: `EvidenceStatus` — Aggregate status.
- `nested_folds`: `list[NestedFoldEvidence]` — Evidence across all nested folds.
- `parameter_robustness`: `list[ParameterRobustnessCandidate]` — Parameter space robustness evaluation.
- `psr`: `PSRResult` — Probabilistic Sharpe Ratio result.
- `dsr`: `DSRResult` — Deflated Sharpe Ratio result.
- `bootstrap_intervals`: `dict[str, BootstrapConfidenceIntervals]` — Bootstrap CIs for key metrics.
- `monte_carlo`: `MonteCarloRobustnessResult` — Monte Carlo simulation results.
- `cost_stress`: `list[CostStressResult]` — Cost stress evaluation across multipliers.
- `execution_stress`: `list[ExecutionStressResult]` — Swing execution stress evaluations.
- `policy_version`: `str` — Policy version string.
- `policy_hash`: `str` — SHA-256 hash of configured robustness policy.
- `data_hash`: `str` — Underlying dataset hash.
- `evidence_hash`: `str` — Deterministic SHA-256 evidence bundle hash.
- `created_at`: `datetime` — Creation timestamp.

---

## Database Schema (`strategy_robustness_evaluations`)

```sql
CREATE TABLE IF NOT EXISTS strategy_robustness_evaluations (
    robustness_id VARCHAR PRIMARY KEY,
    run_id VARCHAR NOT NULL,
    experiment_family_id VARCHAR,
    strategy_name VARCHAR NOT NULL,
    strategy_version VARCHAR NOT NULL,
    selected_trial_id VARCHAR,
    evidence_status VARCHAR NOT NULL,
    psr_json JSON NOT NULL,
    dsr_json JSON NOT NULL,
    bootstrap_json JSON NOT NULL,
    monte_carlo_json JSON NOT NULL,
    cost_stress_json JSON NOT NULL,
    execution_stress_json JSON NOT NULL,
    parameter_robustness_json JSON NOT NULL,
    nested_folds_json JSON NOT NULL,
    policy_version VARCHAR NOT NULL,
    policy_hash VARCHAR NOT NULL,
    data_hash VARCHAR NOT NULL,
    evidence_hash VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_robustness_lookup
    ON strategy_robustness_evaluations(strategy_name, strategy_version, run_id);
CREATE INDEX IF NOT EXISTS idx_robustness_family
    ON strategy_robustness_evaluations(experiment_family_id);
CREATE INDEX IF NOT EXISTS idx_robustness_evidence
    ON strategy_robustness_evaluations(evidence_hash);
```
