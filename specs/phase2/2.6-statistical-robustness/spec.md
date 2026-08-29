# Phase 2.6 — Statistically Defensible Research Framework

## Objective

Upgrade strategy validation from ordinary expanding walk-forward validation to a statistically defensible research framework.
Establish nested walk-forward folds with sealed final OOS testing, dual-boundary purging and post-test embargoing, parameter plateau/sensitivity robustness selection, Probabilistic Sharpe Ratio (PSR), trial-registry-backed Deflated Sharpe Ratio (DSR), deterministic block bootstrap, Monte Carlo path resampling, multi-tiered cost stress with slippage and liquidity factors, and swing execution stress scenarios.

## Requirements

### 1. Nested Walk-Forward Validation & Single Authoritative Splitter
- One authoritative `NestedWalkForwardSplitter` generates fold boundaries and index/date partitions consumed by `RobustnessEvaluator`.
- Explicitly separate each fold into three stages:
  - `TRAIN`: Used for candidate discovery and parameter evaluation.
  - `VALIDATION`: Used strictly in conjunction with `TRAIN` for candidate selection according to an explicit, versioned selection policy.
  - `FINAL_OOS_TEST`: Strictly sealed during parameter selection. Final OOS data, results, labels, returns, statistics, and metadata must never influence candidate discovery or selection. Changing future final OOS data must have zero effect on selected parameters. Final OOS is evaluated exactly once after candidate selection is frozen.
- Persist for every fold:
  - fold identifier (`fold_id`)
  - train start/end timestamps
  - validation start/end timestamps
  - final-test start/end timestamps
  - actual purged timestamp/index ranges (`purged_train_range`, `purged_val_range`)
  - actual embargoed timestamp/index ranges (`embargoed_ranges`)
  - input dataset IDs and exact data/content hashes
  - frame-certification IDs
  - policy/version identifiers
  - selected candidate parameters and parameter hash (`selected_parameter_hash`)
  - actual selected research trial ID (`selected_trial_id`) from Phase 2.1 trial registry
  - relevant trial-registry references
  - deterministic fold evidence hash (`evidence_hash`)

### 2. Dual-Boundary Purge & Post-Test Embargo
- Purge must protect both stage boundaries:
  - `TRAIN -> VALIDATION`: Purge trailing observations/labels from TRAIN whose outcome overlaps VALIDATION.
  - `VALIDATION -> FINAL_OOS_TEST`: Purge trailing observations/labels from VALIDATION whose outcome overlaps FINAL_OOS_TEST.
- Support configurable `purge_window` (number of bars/periods before boundaries) and `embargo_window` (number of bars/periods after evaluation intervals to prevent leakage into subsequent train folds).
- Post-test embargo: observations within `[test_end, test_end + embargo_window]` must be excluded from entering subsequent training sets.
- Support zero window (`0`), reject negative values with a clear error.

### 3. Parameter Robustness Policy
- Disallow selecting parameters solely on maximum raw TRAIN Sharpe.
- Evaluate candidate neighborhoods across the parameter grid.
- Compute for every candidate:
  - `neighbor_mean`, `neighbor_std`, `neighbor_min` (minimum performance among neighbors)
  - `sensitivity_score` (normalized rate of drop-off / variance across neighbors)
  - `plateau_neighbor_count`, `neighbor_count`, `plateau_fraction` (% of neighbors meeting performance threshold `plateau_min_ratio * center_score`), `plateau_width`
  - `train_rank`, `val_rank`, `rank_delta`, and `rank_stability` (computed via Spearman rank correlation / rank displacement between TRAIN and VALIDATION ranks)
  - `aggregate_robustness_score` combining raw performance, plateau stability, low sensitivity, neighbor min, and fold rank stability.
- Ensure broad, stable performance plateaus beat isolated high-Sharpe spikes.
- Persist full candidate evaluations, neighborhood definitions, scores, and selection rationale deterministically.

### 4. Probabilistic Sharpe Ratio (PSR)
- Implement pure, mathematically sound PSR in `experiments/statistical_tests.py` based on Bailey & López de Prado (2012).
- Account for sample size $n$, skewness $\gamma_3$, kurtosis $\gamma_4$, sample non-annualized Sharpe $\widehat{SR}$, and benchmark Sharpe $SR^*$.
- Handle edge cases safely: insufficient observations ($n < n_{min}$), zero variance, constant returns, NaN, Inf, and mathematical domain violations by returning structured results with evidence status `VALID`, `INSUFFICIENT_EVIDENCE`, or `INVALID_INPUT`.
- Fail closed without manufacturing synthetic numeric values on invalid or insufficient input.

### 5. Deflated Sharpe Ratio (DSR) with Authoritative Trial Registry Linkage
- Implement DSR in `experiments/statistical_tests.py` based on Bailey & López de Prado (2014) using the expected maximum Sharpe ratio under the null hypothesis of no skill across $N$ independent trials:
  $$SR_0 = \sqrt{V(\{SR_k\})} \left( (1 - \gamma) \Phi^{-1}\left(1 - \frac{1}{N}\right) + \gamma \Phi^{-1}\left(1 - \frac{1}{N} e^{-1}\right) \right)$$
- Derive the effective trial count $N$ and trial Sharpe distribution directly and authoritatively from the Phase 2.1 trial registry (`research_trials_log` via `DuckDBManager.list_research_trials()`).
- Explicitly reject arbitrary user-supplied trial counts and do NOT fall back to local uncertified candidates for authoritative DSR claims.
- If `experiment_family_id` is missing or cannot be resolved: return `INSUFFICIENT_EVIDENCE` with deterministic reason `MISSING_AUTHORITATIVE_TRIAL_FAMILY`.
- Account for trial multiplicity:
  - Deduplicate idempotent/replay trials by definition identity.
  - Count `succeeded_count`, `failed_count` (which increase multiplicity $N$ even without Sharpe), `invalidated_count`, and `deduplicated_count`.
  - Effective multiplicity $N = \text{succeeded\_count} + \text{failed\_count}$.
  - The Sharpe distribution for variance $V(\{SR_k\})$ contains only valid Sharpe observations from succeeded trials; if fewer than 2 exist, return `INSUFFICIENT_EVIDENCE`.
- Persist experiment family ID, trial IDs, effective count $N$, Sharpe count, succeeded/failed/invalidated/deduplicated counts, trial policy version/hash, DSR output, and evidence status.

### 6. Deterministic Seeded Bootstrap
- Implement deterministic seeded bootstrap in `experiments/statistical_tests.py` supporting i.i.d. and moving block bootstrap.
- Compute confidence intervals (e.g. 95% CI: lower, upper, median) for Total Return, Sharpe Ratio, Expectancy (period return and net trade expectancy when fills provided), and Maximum Drawdown.
- Ensure identical input + configuration + seed yields identical output.

### 7. Monte Carlo Robustness Simulation
- Resample trade sequences and return paths using seeded simulation to estimate:
  - Probability of negative period $P(\text{Return} < 0)$
  - Probability of drawdown exceeding threshold $P(\text{MaxDD} > \text{threshold})$
  - Max Drawdown distribution (percentiles: 5th, 50th, 95th, 99th)
  - Sharpe ratio distribution (percentiles: 5th, 50th, 95th)
  - Capital ruin probability $P(\text{Equity} \le \text{ruin\_level})$ calculated directly from simulated cumulative equity paths ($ruin\_level = starting\_capital \times (1 - ruin\_threshold)$).
- Persist `ruin_definition`, `ruin_level`, `capital_ruin_probability`, percentiles, simulations, seed.

### 8. Multi-Tiered Cost Stress & Slippage/Liquidity
- Evaluate baseline ($1.0\times$), $1.5\times$, $2.0\times$, and $3.0\times$ transaction-cost scenarios on causally valid out-of-sample (OOS) evidence.
- Apply configured `slippage_stress_bps` and `liquidity_stress_factor` to stressed runs while keeping baseline $1.0\times$ unperturbed.
- Persist `multiplier`, `slippage_bps_override`, `liquidity_stress_factor`, `cost_schedule_summary`, and net metrics.

### 9. Swing Execution Stress
- Provide configurable execution stress scenarios evaluated on OOS evidence:
  - Overnight gap risk (`overnight_gap_stress`)
  - Stop slippage (`stop_slippage_stress`)
  - 1-bar execution delay (`execution_delay_1bar`)
  - Deterministic seeded missed fills (`missed_fills`)
  - Reduced liquidity constraints (`reduced_liquidity`)
- Perturb execution economics / fills / returns deterministically without fabricating precision.

### 10. Structured Robustness Result, Evidence Hash Binding & Persistence
- Define typed Pydantic models for all Phase 2.6 results in `experiments/robustness.py` and `experiments/statistical_tests.py`.
- Final `evidence_hash` binds all semantic robustness evidence (nested folds, parameter robustness, PSR, DSR, bootstrap, Monte Carlo, cost stress, execution stress, policy version/hash, data hash, frame cert, trial lineage, actual selected trial IDs, purge/embargo boundaries). Excludes non-deterministic timestamps (`created_at`).
- Overall `evidence_status` fails closed (`INSUFFICIENT_EVIDENCE`) if any required component is insufficient.
- Persist robustness bundles immutably in DuckDB (`strategy_robustness_evaluations`): identical replay is idempotent; conflicting payload for an existing identity fails atomically.

## Non-goals

- No Phase 2.7 strategy × regime/asset-state matrix or evidence.
- No Phase 2.8 strategy scorecards or ranking.
- No Phase 2.9 adaptive selector or Phase 2.10 meta-selector.
- No live order routing or modifications to broker execution.
- No direct push to protected main branch (all changes land via PR with full green CI).

