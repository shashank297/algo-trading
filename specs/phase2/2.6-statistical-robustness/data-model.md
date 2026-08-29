# Phase 2.6 Data Model: Statistically Defensible Research Framework

## Entities & Enums

### 1. `EvidenceStatus` (Enum)
- `VALID`: Valid calculation with sufficient evidence and satisfying all domain constraints.
- `INSUFFICIENT_EVIDENCE`: Sample size below minimum threshold, missing required trial registry evidence, or observations insufficient.
- `INVALID_INPUT`: Inputs contain NaN, Inf, non-positive variance, or violate parameter constraints.

### 2. `TrialCountSource` (Enum)
- `PHASE2_1_REGISTRY`: Authoritative trial multiplicity count derived from Phase 2.1 trial registry.
- `MANUAL_STATISTICAL_INPUT`: Statistical calculation input without authoritative registry verification (cannot produce `VALID` evidence).

### 3. `ExpectancyBasis` (Enum)
- `NET_TRADE_PNL`: Resamples net trade PnL observations from actual fills; units in monetary currency (e.g. ₹ per trade).
- `PERIOD_RETURN`: Resamples period returns; units in decimal percentage return per period.

### 4. `PSRResult` (Pydantic Model)
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

### 5. `DSRResult` (Pydantic Model)
- `dsr_value`: `float | None` — Deflated Sharpe Ratio in $[0, 1]$.
- `expected_max_sharpe`: `float | None` — $SR_0$ expected maximum Sharpe under null hypothesis.
- `annualized_expected_max_sharpe`: `float | None` — Annualized $SR_0$.
- `sample_sharpe`: `float | None` — Sample non-annualized Sharpe ratio.
- `annualized_sharpe`: `float | None` — Annualized Sharpe ratio.
- `variance_trials`: `float | None` — Estimated variance of Sharpe ratios across trials $V(\{SR_k\})$.
- `effective_trials`: `int` — Effective independent selection multiplicity count $N$ from authoritative registry ($succeeded + failed$).
- `sharpe_count`: `int` — Count of valid Sharpe observations used for variance estimation.
- `succeeded_count`: `int` — Count of succeeded trials.
- `failed_count`: `int` — Count of failed genuine selection trials (included in multiplicity $N$).
- `invalidated_trials`: `int` — Count of invalidated trials.
- `deduplicated_count`: `int` — Count of deduplicated idempotent replay trials.
- `total_trials`: `int` — Total raw trial records in experiment family query scope.
- `experiment_family_id`: `str | None` — Authoritative trial registry experiment family ID.
- `trial_count_source`: `TrialCountSource` — Provenance source (`PHASE2_1_REGISTRY` or `MANUAL_STATISTICAL_INPUT`).
- `trial_ids`: `list[str]` — List of trial IDs evaluated.
- `trial_policy_version`: `str` — Version string of trial selection policy.
- `trial_policy_hash`: `str` — SHA-256 hash of trial selection policy.
- `status`: `EvidenceStatus` — Evaluation status.
- `reason`: `str | None` — Status explanation (e.g. `MISSING_AUTHORITATIVE_TRIAL_FAMILY`).

### 6. `BootstrapConfidenceIntervals` (Pydantic Model)
- `metric_name`: `str` — Metric identifier (`total_return`, `sharpe`, `expectancy`, `max_drawdown`).
- `lower_bound`: `float` — Lower percentile bound (e.g. 2.5th for 95% CI).
- `upper_bound`: `float` — Upper percentile bound (e.g. 97.5th for 95% CI).
- `median`: `float` — Resampled median value.
- `point_estimate`: `float` — Original point estimate.
- `expectancy_basis`: `ExpectancyBasis` — `NET_TRADE_PNL` when fills exist, `PERIOD_RETURN` otherwise.
- `confidence_level`: `float` — Configured confidence level (e.g. 0.95).
- `resamples`: `int` — Number of bootstrap resamples.
- `method`: `str` — `IID` or `MOVING_BLOCK`.
- `block_size`: `int | None` — Block size if block bootstrap.
- `seed`: `int` — Seed used for deterministic reproducibility.
- `status`: `EvidenceStatus` — Status.
- `reason`: `str | None` — Status explanation.

### 7. `MonteCarloRobustnessResult` (Pydantic Model)
- `simulations`: `int` — Number of simulation paths (e.g. 1000).
- `seed`: `int` — Simulation seed.
- `prob_negative_return`: `float | None` — $P(\text{Return} < 0)$.
- `prob_drawdown_exceeds_threshold`: `float | None` — $P(\text{MaxDD} > \text{threshold})$.
- `drawdown_threshold`: `float` — Drawdown threshold (e.g. 0.20 for 20%).
- `max_drawdown_percentiles`: `dict[str, float]` — `{"p5": ..., "p50": ..., "p95": ..., "p99": ...}`.
- `sharpe_percentiles`: `dict[str, float]` — `{"p5": ..., "p50": ..., "p95": ...}`.
- `capital_ruin_probability`: `float | None` — Estimated capital ruin probability calculated directly from cumulative simulated equity paths.
- `ruin_threshold`: `float` — Ruin equity fraction threshold (e.g. 0.50 for 50% capital loss).
- `ruin_level`: `float | None` — Capital ruin equity floor ($starting\_capital \times (1 - ruin\_threshold)$).
- `ruin_definition`: `str` — Description of capital ruin rule (`cumulative_equity_breach_below_ruin_level`).
- `status`: `EvidenceStatus` — Status.
- `reason`: `str | None` — Status explanation.

### 8. `ParameterRobustnessCandidate` (Pydantic Model)
- `parameters`: `dict[str, Any]` — Parameter values.
- `parameter_hash`: `str` — SHA-256 parameter hash.
- `train_score`: `float` — Raw performance score on TRAIN.
- `val_score`: `float | None` — Raw performance score on VALIDATION.
- `neighbor_parameters`: `list[dict[str, Any]]` — Neighboring candidates in grid.
- `neighbor_scores`: `list[float]` — Scores of neighboring candidates.
- `neighbor_mean`: `float` — Mean score across neighbors.
- `neighbor_std`: `float` — Score standard deviation across neighbors.
- `neighbor_min`: `float` — Minimum score across neighbors.
- `plateau_neighbor_count`: `int` — Count of neighbors meeting threshold (`neighbor_score >= plateau_min_ratio * center_score`).
- `neighbor_count`: `int` — Total count of neighbors.
- `plateau_fraction`: `float` — Fraction of neighbors on plateau (`plateau_neighbor_count / max(1, neighbor_count)`).
- `plateau_width`: `float` — Plateau neighborhood span.
- `plateau_score`: `float` — Plateau score (`plateau_fraction`).
- `sensitivity_score`: `float` — Normalized drop-off / sensitivity metric.
- `train_rank`: `int` — 1-based candidate rank on TRAIN.
- `val_rank`: `int | None` — 1-based candidate rank on VALIDATION.
- `rank_delta`: `int | None` — Absolute rank difference $|train\_rank - val\_rank|$.
- `rank_stability`: `float` — Cross-fold rank stability score computed from ranking consistency.
- `aggregate_robustness_score`: `float` — Composite robustness score combining raw score, plateau, low sensitivity, neighbor min, and rank stability.
- `selected`: `bool` — Whether candidate is selected by policy.
- `selection_reason`: `str | None` — Rationale for selection.

### 9. `NestedFoldEvidence` (Pydantic Model)
- `fold_id`: `str` — Fold identifier (e.g. `nfold-001`).
- `train_start`: `datetime` — Train window start.
- `train_end`: `datetime` — Train window end.
- `val_start`: `datetime` — Validation window start.
- `val_end`: `datetime` — Validation window end.
- `test_start`: `datetime` — Final OOS test window start.
- `test_end`: `datetime` — Final OOS test window end.
- `purge_window`: `int` — Purge bar window.
- `embargo_window`: `int` — Embargo bar window.
- `purged_train_range`: `list[str]` — Actual purged timestamp range at TRAIN -> VAL boundary.
- `purged_val_range`: `list[str]` — Actual purged timestamp range at VAL -> FINAL_OOS boundary.
- `embargoed_ranges`: `list[str]` — Actual embargoed timestamp ranges for future training sets.
- `dataset_snapshot_ids`: `dict[str, str | None]` — Dataset snapshot IDs per symbol.
- `contributing_dataset_ids`: `list[str]` — Contributing dataset identifiers.
- `dataset_content_hashes`: `dict[str, str]` — Exact content hashes per symbol dataset.
- `train_data_hash`: `str` — SHA-256 data hash of TRAIN slice.
- `val_data_hash`: `str` — SHA-256 data hash of VALIDATION slice.
- `test_data_hash`: `str` — SHA-256 data hash of FINAL OOS slice.
- `frame_certification_id`: `str | None` — Frame certification ID.
- `selected_parameters`: `dict[str, Any]` — Parameters selected on TRAIN/VAL.
- `selected_parameter_hash`: `str` — SHA-256 parameter hash of selected candidate.
- `selected_trial_id`: `str | None` — Actual trial registry ID from Phase 2.1 registry.
- `train_metrics`: `dict[str, float]` — Metrics on TRAIN.
- `val_metrics`: `dict[str, float]` — Metrics on VALIDATION.
- `final_oos_metrics`: `dict[str, float]` — Metrics on FINAL OOS TEST.
- `evidence_hash`: `str` — Deterministic fold evidence hash.

### 10. `CostStressResult` (Pydantic Model)
- `multiplier`: `float` — Cost multiplier ($1.0, 1.5, 2.0, 3.0$).
- `slippage_bps_override`: `float | None` — Stressed slippage in bps applied to trade volume.
- `liquidity_stress_factor`: `float | None` — Liquidity penalty factor applied to impact/capacity.
- `metrics`: `dict[str, float]` — Recomputed net performance metrics (Sharpe, CAGR, MaxDD, Total Return).
- `cost_schedule_summary`: `dict[str, Any]` — Summary of cost assumptions applied.
- `status`: `EvidenceStatus` — Scenario status (`VALID` or `INSUFFICIENT_EVIDENCE`).
- `reason`: `str | None` — Reason when evidence is missing.

### 11. `ExecutionStressResult` (Pydantic Model)
- `scenario_name`: `str` — Name of execution scenario (`overnight_gap_stress`, `stop_slippage_stress`, `execution_delay_1bar`, `missed_fills`, `reduced_liquidity`).
- `perturbation_params`: `dict[str, Any]` — Configured perturbation parameters.
- `metrics`: `dict[str, float]` — Stressed net metrics evaluated on OOS evidence.
- `seed`: `int | None` — Resampling/perturbation seed.
- `status`: `EvidenceStatus` — Scenario status (`VALID` or `INSUFFICIENT_EVIDENCE`).
- `reason`: `str | None` — Reason when evidence is missing.

### 12. `RobustnessBundle` (Pydantic Model)
- `robustness_id`: `str` — Deterministic SHA-256 identity.
- `run_id`: `str` — Associated strategy run ID.
- `experiment_family_id`: `str | None` — Experiment family ID if registered.
- `strategy_name`: `str` — Strategy name.
- `strategy_version`: `str` — Strategy version.
- `selected_trial_id`: `str | None` — Real selected trial ID.
- `evidence_status`: `EvidenceStatus` — Aggregate status (fails closed if any required component is insufficient).
- `nested_folds`: `list[NestedFoldEvidence]` — Evidence across all nested folds.
- `parameter_robustness`: `list[ParameterRobustnessCandidate]` — Parameter space robustness evaluation.
- `psr`: `PSRResult` — Probabilistic Sharpe Ratio result.
- `dsr`: `DSRResult` — Deflated Sharpe Ratio result with trial multiplicity.
- `bootstrap_intervals`: `dict[str, BootstrapConfidenceIntervals]` — Bootstrap CIs for key metrics.
- `monte_carlo`: `MonteCarloRobustnessResult` — Monte Carlo simulation results.
- `cost_stress`: `list[CostStressResult]` — Cost stress evaluation across multipliers.
- `execution_stress`: `list[ExecutionStressResult]` — Swing execution stress evaluations.
- `policy_version`: `str` — Policy version string.
- `policy_hash`: `str` — SHA-256 hash of configured robustness policy.
- `data_hash`: `str` — Underlying dataset hash.
- `evidence_hash`: `str` — Deterministic SHA-256 evidence bundle hash binding all semantic evidence.
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
