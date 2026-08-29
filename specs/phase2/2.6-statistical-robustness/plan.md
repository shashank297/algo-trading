# Phase 2.6 Implementation Plan: Statistically Defensible Research Framework

## Summary
Upgrade strategy validation to a statistically defensible research framework by implementing pure statistical tests (PSR, DSR, bootstrap, Monte Carlo) in `experiments/statistical_tests.py` and nested walk-forward, parameter robustness selection, multi-tier cost stress, swing execution stress, DuckDB persistence, and CLI operations in `experiments/robustness.py`.

## Architecture & Principles Check

| Principle / Invariant | Compliance Strategy |
|---|---|
| **Sealed Final OOS** | Parameter discovery and selection use `TRAIN` + `VALIDATION` only. `FINAL_OOS_TEST` is evaluated strictly after selection is frozen. Altering future test data cannot affect selected parameters. |
| **Authoritative Trial Linkage** | Effective trial count $N$ and trial Sharpe variance for DSR are derived directly from the Phase 2.1 trial registry (`DuckDBManager.list_research_trials()`). Arbitrary user counts are rejected. |
| **Deterministic Resampling** | Bootstrap confidence intervals and Monte Carlo simulations use explicit seeds, fixed algorithms, and return reproducible outputs. |
| **No Baseline Mutation** | Cost and execution stress scenarios evaluate independent perturbed runs without modifying baseline backtest results or data hashes. |
| **DuckDB Immutability** | Persisted robustness evaluations in `strategy_robustness_evaluations` are immutable with sha256 evidence hashes; identical replay is idempotent; conflicting payload fails atomically. |
| **Live Routing Disabled** | Phase 2.6 is purely research-time statistical evaluation; live execution paths remain disabled. |

## Technical Design & Modules

### 1. Pure Statistical Tests (`experiments/statistical_tests.py`)
- `ProbabilisticSharpeRatio`: Analytical PSR based on Bailey & López de Prado (2012) handling non-normality (skewness, kurtosis) and benchmark threshold. Returns typed `PSRResult`.
- `DeflatedSharpeRatio`: DSR based on Bailey & López de Prado (2014) estimating the expected maximum Sharpe under the null hypothesis given effective trial count $N$ and variance of trial Sharpes. Returns typed `DSRResult`.
- `DeterministicBootstrap`: i.i.d. and block bootstrap for return, Sharpe, expectancy, and max drawdown confidence intervals with explicit seeds. Returns typed `BootstrapConfidenceIntervals`.
- `MonteCarloRobustness`: Trade/return resampling to compute drawdown distributions, ruin probability, and negative period probability. Returns typed `MonteCarloRobustnessResult`.

### 2. Robustness Framework & Nested Walk-Forward (`experiments/robustness.py`)
- `NestedWalkForwardSplitter`: Creates 3-way fold splits (`TRAIN`, `VALIDATION`, `FINAL_OOS_TEST`) with configurable `purge_window` and `embargo_window`.
- `ParameterRobustnessSelector`: Discovers and evaluates parameter candidates on TRAIN/VAL; evaluates parameter neighborhoods, plateau widths, sensitivity drop-offs, and rank stability across folds.
- `StressScenarioEngine`: Evaluates cost stress ($1.0\times, 1.5\times, 2.0\times, 3.0\times$, slippage, liquidity) and swing execution stress (overnight gap, stop slippage, delay, missed fills).
- `RobustnessEvaluator`: Orchestrates the complete end-to-end Phase 2.6 robustness evaluation, binding trials from the Phase 2.1 registry and generating the final immutable `RobustnessBundle`.

### 3. DuckDB Schema Evolution & Persistence
- `storage/migrations/022_phase2_6_robustness.sql`: Create `strategy_robustness_evaluations` and lookup indexes.
- `storage/duckdb_manager.py`: Add `save_robustness_evaluation()`, `get_robustness_evaluation()`, `list_robustness_evaluations()`.

### 4. CLI, Configuration & Public Exports
- `research.py`: Add `--command robustness` with subcommands / options.
- `config/config.example.yaml`: Add `statistical_robustness` policy block.
- `experiments/__init__.py`: Export public Phase 2.6 models and services.
- `.github/workflows/ci.yml`: Add `experiments/robustness.py` and `experiments/statistical_tests.py` to the $\ge 95\%$ critical coverage threshold.

### 5. Verification & Test Suite
- `tests/test_statistical_tests.py`: Unit tests for PSR, DSR, bootstrap, Monte Carlo against independent analytical references and edge cases.
- `tests/test_robustness.py`: Integration tests for nested walk-forward, purge/embargo, parameter plateau selection, cost/execution stress, trial registry linkage, and immutable DuckDB persistence.
