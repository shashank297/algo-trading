# Phase 2.6 Implementation Plan: Statistically Defensible Research Framework

## Summary
Upgrade strategy validation to a statistically defensible research framework by implementing pure statistical tests (PSR, DSR, bootstrap, Monte Carlo) in `experiments/statistical_tests.py` and nested walk-forward, parameter plateau robustness selection, multi-tier cost stress with slippage/liquidity, swing execution stress, DuckDB persistence, and CLI operations in `experiments/robustness.py`.

## Architecture & Principles Check

| Principle / Invariant | Compliance Strategy |
|---|---|
| **Sealed Final OOS** | Parameter discovery and selection use `TRAIN` + `VALIDATION` only. `FINAL_OOS_TEST` is evaluated strictly after selection is frozen. Altering future test data cannot affect selected parameters. |
| **Authoritative Trial Linkage** | Effective trial count $N$ (accounting for SUCCEEDED, FAILED, INVALIDATED, deduplicated replay trials) and trial Sharpe variance for DSR are derived directly from the Phase 2.1 trial registry (`DuckDBManager.list_research_trials()`). Missing/unregistered family fails closed with `INSUFFICIENT_EVIDENCE`. |
| **Deterministic Resampling** | Bootstrap confidence intervals and Monte Carlo simulations use explicit seeds, fixed algorithms, and return reproducible outputs. Monte Carlo capital ruin is calculated directly from cumulative simulated equity paths ($ruin\_level = starting\_capital \times (1 - ruin\_threshold)$). |
| **Dual Purge & Post-Test Embargo** | Purge protects both `TRAIN -> VAL` and `VAL -> FINAL_OOS` boundaries. Post-test embargo excludes `[test_end, test_end + embargo_window]` observations from entering future training sets. |
| **Single Authoritative Splitter** | `NestedWalkForwardSplitter` is the single authoritative source of truth for fold boundaries, purge ranges, and embargo intervals, consumed directly by `RobustnessEvaluator`. |
| **Parameter Plateau Robustness** | Candidates are evaluated across parameter neighborhoods computing neighbor mean, std, min, plateau fraction (% of neighbors meeting threshold), sensitivity drop-off, and rank stability across folds (Spearman rank correlation / displacement). |
| **Causal OOS Stress Testing** | Cost stress ($1.0\times, 1.5\times, 2.0\times, 3.0\times$ with slippage and liquidity factor) and swing execution stress (overnight gap, stop slippage, delay, missed fills, reduced liquidity) are evaluated on concatenated out-of-sample (OOS) evidence without mutating baseline runs. |
| **DuckDB Immutability & Evidence Hash** | Persisted robustness evaluations in `strategy_robustness_evaluations` are immutable with sha256 evidence hashes binding all semantic results; identical replay is idempotent; conflicting payload fails atomically. |
| **Live Routing Disabled** | Phase 2.6 is purely research-time statistical evaluation; live execution paths remain disabled. |
| **Protected Main Workflow** | All changes are implemented on `phase2.6-remediation`, verified across full test matrix, submitted via PR, pass all 6 GitHub Actions status checks, merged via protected branch rules, and verified on exact merged main. |

## Technical Design & Modules

### 1. Pure Statistical Tests (`experiments/statistical_tests.py`)
- `compute_psr`: Analytical PSR based on Bailey & López de Prado (2012) handling non-normality (skewness, kurtosis) and benchmark threshold. Returns typed `PSRResult`.
- `compute_dsr`: DSR based on Bailey & López de Prado (2014) estimating the expected maximum Sharpe under the null hypothesis given effective trial count $N$ and variance of trial Sharpes. Fails closed if authoritative trial family is missing or unregistered. Returns typed `DSRResult`.
- `compute_bootstrap_confidence_intervals`: i.i.d. and moving block bootstrap for return, Sharpe, expectancy, and max drawdown confidence intervals with explicit seeds. Returns typed `BootstrapConfidenceIntervals`.
- `compute_monte_carlo_robustness`: Path resampling to compute drawdown distributions, capital ruin probability, and negative period probability. Returns typed `MonteCarloRobustnessResult`.

### 2. Robustness Framework & Nested Walk-Forward (`experiments/robustness.py`)
- `NestedWalkForwardSplitter`: Single authoritative splitter creating 3-way fold splits (`TRAIN`, `VALIDATION`, `FINAL_OOS_TEST`) with dual boundary purge (`TRAIN -> VAL` and `VAL -> FINAL_OOS`) and post-test embargo for future training.
- `ParameterRobustnessSelector`: Evaluates candidates on TRAIN/VAL; evaluates parameter neighborhoods, neighbor min, plateau width, plateau fraction, sensitivity drop-offs, and rank stability across folds.
- `StressScenarioEngine`: Evaluates cost stress ($1.0\times, 1.5\times, 2.0\times, 3.0\times$, slippage bps, liquidity stress) and swing execution stress (overnight gap, stop slippage, delay, missed fills, reduced liquidity) on out-of-sample evidence.
- `RobustnessEvaluator`: Orchestrates the complete end-to-end Phase 2.6 robustness evaluation, binding trials from the Phase 2.1 registry, mapping winner to actual real `trial_id`, and generating the final immutable `RobustnessBundle`.

### 3. DuckDB Schema Evolution & Persistence
- `storage/migrations/022_phase2_6_robustness.sql`: Create `strategy_robustness_evaluations` and lookup indexes.
- `storage/duckdb_manager.py`: `save_robustness_evaluation()`, `get_robustness_evaluation()`, `list_robustness_evaluations()`.

### 4. CLI, Configuration & Public Exports
- `research.py`: `--command robustness` with subcommands / options.
- `config/config.example.yaml`: `statistical_robustness` policy block.
- `experiments/__init__.py`: Export public Phase 2.6 models and services.
- `.github/workflows/ci.yml`: Enforce $\ge 95\%$ critical coverage threshold on `experiments/robustness.py` and `experiments/statistical_tests.py`.

### 5. Verification & Test Suite
- `tests/test_statistical_tests.py`: Unit and adversarial tests for PSR, DSR (fail-closed, multiplicity, invalidated, replays), bootstrap, Monte Carlo (capital ruin).
- `tests/test_robustness.py`: Integration tests for nested walk-forward (dual purge, post-test embargo, sealed OOS), parameter plateau selection, cost/execution stress (slippage, liquidity), real trial ID mapping, and immutable DuckDB persistence.

