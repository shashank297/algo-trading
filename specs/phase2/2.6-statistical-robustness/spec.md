# Phase 2.6 — Statistically Defensible Research Framework

## Objective

Upgrade strategy validation from ordinary expanding walk-forward validation to a statistically defensible research framework.
Establish nested walk-forward folds with sealed final OOS testing, purging and embargoing, parameter plateau/sensitivity robustness selection, Probabilistic Sharpe Ratio (PSR), trial-registry-backed Deflated Sharpe Ratio (DSR), deterministic block bootstrap, Monte Carlo path resampling, multi-tiered cost stress, and swing execution stress scenarios.

## Requirements

### 1. Nested Walk-Forward Validation
- Explicitly separate each fold into three stages:
  - `TRAIN`: Used for candidate discovery and parameter evaluation.
  - `VALIDATION`: Used strictly in conjunction with `TRAIN` for candidate selection according to an explicit, versioned selection policy.
  - `FINAL_OOS_TEST`: Strictly sealed during parameter selection. Final OOS data, results, labels, returns, statistics, and metadata must never influence candidate discovery or selection. Changing future final OOS data must have zero effect on selected parameters. Final OOS is evaluated exactly once after candidate selection is frozen.
- Persist for every fold:
  - fold identifier
  - train start/end timestamps
  - validation start/end timestamps
  - final-test start/end timestamps
  - purge boundaries
  - embargo boundaries
  - input dataset IDs and exact data/content hashes
  - frame-certification IDs
  - policy/version identifiers
  - selected candidate parameters and trial ID
  - relevant trial-registry references
  - deterministic evidence hash

### 2. Purge & Embargo
- Support configurable `purge_window` (number of bars/periods before validation/test boundaries to remove overlapping trade horizons) and `embargo_window` (number of bars/periods after validation/test intervals to prevent leakage into subsequent train folds).
- Support zero window (`0`), reject negative values with a clear error.
- Enforce deterministic timestamp boundary calculations around fold boundaries for overlapping positions and label horizons.

### 3. Parameter Robustness Policy
- Disallow selecting parameters solely on maximum raw TRAIN Sharpe.
- Evaluate candidate neighborhoods across the parameter grid.
- Compute:
  - neighbor performance (mean, standard deviation, minimum)
  - parameter sensitivity (gradient / variance across immediate neighbors)
  - plateau width and plateau score (% of neighbors meeting performance threshold)
  - rank stability across train/val folds (Spearman rank correlation or rank variance)
  - aggregate robustness score combining raw performance, plateau stability, low sensitivity, and fold rank stability.
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
- Explicitly reject arbitrary user-supplied trial counts for authoritative DSR.
- Define and audit the treatment of trials:
  - `SUCCEEDED` and `FAILED` candidate trials are included in multiplicity accounting.
  - `INVALIDATED` trials (e.g. data corruption/bug before valid evaluation) are accounted for according to documented policy.
  - Replays/idempotent trials are deduplicated by definition hash.
- Persist experiment family ID, query scope, trial IDs, effective count, DSR output, and evidence status.
- Fail closed if authoritative trial lineage cannot be resolved.

### 6. Deterministic Seeded Bootstrap
- Implement deterministic seeded bootstrap in `experiments/statistical_tests.py` supporting i.i.d. and block bootstrap (moving block bootstrap with configurable block size).
- Compute confidence intervals (e.g. 95% CI: lower, upper, median) for Total Return, Sharpe Ratio, Expectancy, and Maximum Drawdown.
- Ensure identical input + configuration + seed yields identical output.
- Fail safely on insufficient observations.

### 7. Monte Carlo Robustness Simulation
- Resample trade sequences and return paths using seeded simulation to estimate:
  - Probability of negative period $P(\text{Return} < 0)$
  - Probability of drawdown exceeding threshold $P(\text{MaxDD} > \text{threshold})$
  - Max Drawdown distribution (percentiles: 5th, 50th, 95th, 99th)
  - Sharpe ratio distribution (percentiles: 5th, 50th, 95th)
  - Capital ruin probability proxy $P(\text{Equity} \le \text{ruin\_level})$
- Treat outputs as model-based robustness estimates with explicit assumptions.

### 8. Multi-Tiered Cost Stress
- Automatically evaluate baseline ($1.0\times$), $1.5\times$, $2.0\times$, and $3.0\times$ transaction-cost scenarios without mutating the baseline backtest result.
- Support configurable slippage and liquidity stress.
- Persist stress-scenario metrics independently alongside baseline hashes.
- Mathematically ensure $2.0\times$ costs worsens net performance whenever gross trade economics are unchanged and trades occur.

### 9. Execution Stress
- Provide configurable swing execution stress perturbations:
  - Overnight gap risk
  - Stop slippage
  - 1-bar execution delay
  - Deterministic seeded missed fills
  - Liquidity/participation rate constraints
- Model perturbations as independent research-time scenario evaluations.

### 10. Structured Robustness Result & Persistence
- Define typed Pydantic models / dataclasses for all Phase 2.6 results in `experiments/robustness.py` and `experiments/statistical_tests.py`.
- Add migration `022_phase2_6_robustness.sql` creating `strategy_robustness_evaluations` and indices.
- Persist robustness bundles immutably in DuckDB: identical replay is idempotent; conflicting payload for an existing identity fails atomically.
- Preserve existing strategy promotion rules (Phase 2.6 persists evidence for downstream evaluation without altering existing promotion gates).

## Non-goals

- No Phase 2.7 strategy × regime/asset-state matrix or evidence.
- No Phase 2.8 strategy scorecards or ranking.
- No Phase 2.9 adaptive selector or Phase 2.10 meta-selector.
- No live order routing or modifications to broker execution.
- No intraday order-book or microstructure simulation.
