# Feature Specification: Phase 2.1 — Immutable Research Trial Registry

## 1. Purpose & Core Invariant

Phase 2.1 creates an immutable and auditable research-trial registry for the algorithmic trading platform.

The registry exists so later statistical controls such as:
- Probabilistic Sharpe Ratio (PSR)
- Deflated Sharpe Ratio (DSR)
- Multiple-testing correction (e.g. White's Reality Check, Hansen's SPA, Family-Wise Error Rate / FDR)
- Parameter robustness analysis
- Strategy-selection validation
- Meta-selector validation

can use the **ACTUAL number of research attempts** rather than only the winning candidates.

### Central Invariant
> **"Every materially distinct attempted research candidate is retained, including unsuccessful candidates, so future multiple-testing and Deflated Sharpe analysis can use the real research search count."**

Phase 2.1 does NOT implement PSR or DSR yet; it establishes the trustworthy trial history and immutability controls required to implement those correctly later.

---

## 2. Existing Work & Foundation to Preserve

The `phase2/2.1-research-trial-registry` branch contains the core foundation that must be preserved and extended:
- `experiments/trials.py` (`ExperimentFamilySpec`, `ResearchTrial`, `TrialStatus`, `canonical_hash`)
- `storage/migrations/014_research_trials.sql` (schema for `experiment_families` and `research_trials_log`)
- DuckDB family & trial registration APIs in `storage/duckdb_manager.py`
- Atomic trial-budget reservation
- Lifecycle transition APIs (`PLANNED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `INVALIDATED`, `CANCELLED`)
- Summary and read APIs
- Interrupted-trial recovery

---

## 3. Detailed Requirements & Domain Models

### 3.1 ExperimentFamilySpec
`ExperimentFamilySpec` represents a pre-registered research hypothesis and search budget.
- Required attributes:
  - `experiment_family_id` (str)
  - `created_at` (datetime UTC)
  - `hypothesis` (str, non-empty)
  - `strategy_names` (list[str], non-empty)
  - `strategy_versions` (list[str], non-empty)
  - `universe_snapshot_id` (str)
  - `timeframe` (str)
  - `feature_versions` (list[str], non-empty)
  - `cost_model_version` (str)
  - `parameter_space` (dict[str, Any])
  - `maximum_trials` (int > 0)
  - `selection_metric` (str)
  - `walk_forward_design` (dict[str, Any])
  - `regime_conditions` (dict[str, Any], default {})
  - `asset_cluster_conditions` (dict[str, Any], default {})
  - `source_revision` (str)
  - `operator_notes` (str | None)
- **Immutability Invariant**: Once research begins (first trial reserved/run), the material research definition (`hypothesis`, strategy set, strategy versions, universe, timeframe, feature design, parameter search space, maximum trial budget, selection policy, walk-forward structure, cost-model definition) is strictly immutable. Attempting to register an altered definition under the same `experiment_family_id` raises a validation error.
- **Budget Immutability**: `maximum_trials` cannot be increased after observing losing trials. New hypotheses or budget extensions require a new experiment family.

### 3.2 ResearchTrial
`ResearchTrial` represents one materially distinct research evaluation.
- Required attributes:
  - `trial_id` (str, deterministic hash of material inputs)
  - `experiment_family_id` (str)
  - `created_at`, `started_at`, `finished_at` (datetime UTC)
  - `strategy_name`, `strategy_version`, `scope`
  - `symbol` (where single-asset) or `universe_snapshot_id` (where portfolio)
  - `timeframe` (str)
  - `parameters` (dict[str, Any])
  - `source_revision` (str)
  - `data_hash` (str)
  - `cost_model_hash` (str)
  - `feature_version` (str | None)
  - `frame_certification_id` (str | None)
  - `fold_id` (str | None)
  - `train_start`, `train_end` (datetime | None)
  - `test_start`, `test_end` (datetime | None)
  - `status` (`TrialStatus`)
  - `metrics` (dict[str, Any] | None)
  - `metrics_hash` (str | None)
  - `selected` (bool, default False)
  - `invalidated` (bool, default False)
  - `invalidation_reason` (str | None)
  - `invalidated_at` (datetime | None)
  - `error_message` (str | None)
  - `parent_trial_id` (str | None)

### 3.3 Trial Counting Semantics
- **What counts as a trial**: Any materially distinct candidate evaluation (differing in strategy, version, parameter configuration, feature version, data hash, universe, timeframe, fold window, cost model, regime condition). Every candidate in a walk-forward parameter search loop constitutes a distinct trial.
- **What does NOT count as a trial**: Reading existing results, report rendering, dashboard queries, reloading data, DB write retries, or exact deterministic resume/reuse of already-completed trials.

### 3.4 Pre-Evaluation Trial-Budget Reservation & Concurrency
- `reserve_research_trial` / `create_research_trial` must atomically verify `consumed + 1 <= maximum_trials` and persist the trial slot **before** backtesting or candidate execution starts.
- If `consumed >= maximum_trials`, fail closed with `RuntimeError` before running candidate $N+1$.
- Concurrency must be protected under DuckDB transactional isolation so concurrent workers cannot exceed `maximum_trials`.

### 3.5 Manager & Evaluator Integrations
1. **`ExperimentSpec` & `MassExperimentSpec`**: Carry optional/explicit `experiment_family_id`. When provided, governs research accounting.
2. **`ExperimentManager`**: Resolves family, constructs `ResearchTrial`, atomically reserves trial slot, marks `RUNNING`, records `SUCCEEDED` with metrics hash on success, or records `FAILED` with error message on exception.
3. **`WalkForwardEvaluator`**: Candidate parameter grid loop registers EVERY evaluated candidate prior to `_run()`. All losing candidates are retained with status `SUCCEEDED`; failing candidates are retained with `FAILED`; the winning candidate is marked `selected = True`.
4. **`MassExperimentManager`**: Propagates `experiment_family_id` to child jobs; exact resume of completed jobs does not increment trial count, while altered configurations register distinct trials.

### 3.6 Invalidation & Interrupted Recovery
- **Invalidation**: Forensic audit operation (`invalidate_trial(trial_id, reason)`). Sets `invalidated = True`, `invalidation_reason`, `invalidated_at` while preserving all original trial parameters, metrics, and lineage. Never deletes trial rows.
- **Interrupted Recovery**: `recover_interrupted_research_trials()` transitions orphan `RUNNING` trials to `FAILED` with `error_message = 'INTERRUPTED_PROCESS'`.

### 3.7 Read-Only Research-Trials CLI
- CLI command in `research.py --command research-trials`:
  - Filters: `--experiment-family-id`, `--trial-id`, `--strategy`, `--status`.
  - Family output: ID, hypothesis, max trials, consumed, remaining, breakdown by status, selected trials count.
  - Trial detail/list: ID, family, strategy, timeframe, parameters, status, selected, invalidated, timestamps.
  - Strictly read-only; no deletion commands.

### 3.8 Documentation & Quality Gates
- Document Phase 2.1 in `docs/research_trials.md`.
- All 15 test categories (Domain, Immutability, Lifecycle, Retention, Budget, Identity, ExperimentManager, MassExperimentManager, WalkForwardEvaluator, Concurrency, Recovery, CLI, Migration, Regression, Statistical Integrity Acceptance) must be deterministic and green.
- Quality gates: 100% pytest pass, global coverage $\ge 80\%$, critical coverage $\ge 95\%$, ruff clean, mypy clean (0 errors), pyright clean (0 errors), compileall clean, pip-audit clean.

---

## 4. Scope Exclusions (Phase 2.2+)
Phase 2.1 explicitly excludes:
- Derived bars (5m, 15m, 30m, 60m)
- Market regimes & regime hysteresis
- Asset states & clusters
- PSR/DSR calculations
- Meta-selector / adaptive strategy selection
- Live broker order routing
