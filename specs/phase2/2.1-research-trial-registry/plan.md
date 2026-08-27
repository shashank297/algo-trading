# Implementation Plan: Phase 2.1 — Immutable Research Trial Registry

## Summary
Implement an immutable, auditable research-trial registry across DuckDB storage, domain models, `ExperimentManager`, `MassExperimentManager`, `WalkForwardEvaluator`, and the CLI. Every attempted research candidate is durably registered and retained (including unsuccessful, losing, and invalidated candidates) to enable rigorous multiple-testing accounting and Deflated Sharpe Ratio (DSR) analysis in subsequent phases.

---

## Constitution & Architecture Check

| Constitution Invariant | Compliance Strategy |
|---|---|
| **Immutable Research Lineage** | Research candidates are durably inserted before execution. Losing and failed trials are permanently retained. |
| **Fail-Closed Budget Control** | Slot reservation occurs prior to candidate evaluation. If `consumed >= maximum_trials`, execution halts with `RuntimeError`. |
| **Transactional Concurrency** | Trial-budget checks and inserts execute inside atomic DuckDB transactions (`with self.transaction():`). |
| **No Synthetic Data / No In-Sample Fallbacks** | Deterministic SHA-256 hashing binds parameter sets, dataset hashes, and metric hashes without shortcuts. |
| **Live Order Routing Disabled** | Phase 2.1 introduces no live broker trading routes (`research.live_trading = false` preserved). |

---

## Technical Design & Modules to Modify

### 1. Storage & Schema Migration
- `storage/migrations/014_research_trials.sql`: Tables `experiment_families` and `research_trials_log` with index on `(experiment_family_id, status)`.
- `storage/duckdb_manager.py`:
  - `register_experiment_family(family)`
  - `get_experiment_family(family_id)`
  - `list_experiment_families()`
  - `create_research_trial(trial)` / `reserve_research_trial(trial)`
  - `get_research_trial(trial_id)`
  - `find_exact_reusable_trial(family_id, ...)`
  - `list_research_trials(family_id, strategy, status)`
  - `transition_research_trial(trial_id, status, metrics, error_message, invalidation_reason)`
  - `mark_trial_selected(trial_id, selected=True)`
  - `invalidate_trial(trial_id, reason)`
  - `remaining_trial_budget(family_id)`
  - `research_trial_summary(family_id)`
  - `recover_interrupted_research_trials()`

### 2. Domain & Experiment Models
- `experiments/trials.py`:
  - `TrialStatus` enum (`PLANNED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `INVALIDATED`, `CANCELLED`).
  - `ExperimentFamilySpec` pydantic model with immutable `definition_hash`.
  - `ResearchTrial` pydantic model with deterministic `trial_id` hash.
- `experiments/models.py`:
  - Update `ExperimentSpec` to include `experiment_family_id: str | None = None`.
  - Update `MassExperimentSpec` to include `experiment_family_id: str | None = None`.

### 3. Manager & Evaluator Integrations
- `experiments/manager.py` (`ExperimentManager`):
  - Pre-execution: check `spec.experiment_family_id`, reserve trial slot, persist as `RUNNING`.
  - Post-execution: update trial to `SUCCEEDED` with metrics and metrics hash on success, or `FAILED` on exception.
- `experiments/walk_forward.py` (`WalkForwardEvaluator`):
  - In parameter optimization / grid search loop: reserve and persist a `ResearchTrial` for EVERY evaluated candidate before `_run()`.
  - Record candidate performance as `SUCCEEDED` or `FAILED`.
  - Mark winning/selected candidate with `selected = True`.
- `experiments/mass.py` (`MassExperimentManager`):
  - Propagate `experiment_family_id` to child jobs and verify deterministic resume semantics.

### 4. CLI & User-Facing Operations
- `research.py`:
  - Add `--command research-trials` with options `--experiment-family-id`, `--trial-id`, `--strategy`, `--status`.
  - Format tabular family summaries and trial listings. Read-only operation.

### 5. Documentation
- `docs/research_trials.md`: Comprehensive guide covering purpose, architecture, lifecycle, budget controls, immutability, recovery, and future DSR integration.

---

## Verification & Test Plan

1. **Unit & Invariant Test Suite (`tests/test_research_trials.py`)**:
   - Family Spec validation & immutability.
   - Deterministic trial hashing.
   - Lifecycle transitions & invalidation.
   - Pre-evaluation budget enforcement & fail-closed $N+1$ candidate blocking.
   - Concurrency race condition prevention.
   - Interrupted recovery (`RUNNING` -> `FAILED / INTERRUPTED_PROCESS`).
   - CLI output & filtering.
   - Walk-forward candidate accounting (losing trials retained, winning trial selected).
   - Statistical integrity end-to-end acceptance test (20 candidates evaluated, 20 persisted, 19 losing, 1 selected, 21st blocked).
2. **Migration Verification (`tests/test_migration_014.py`)**:
   - Fresh DB creation -> 014 applied.
   - Migration runner 001-013 -> 014 upgrade with checksum validation.
3. **Repository Quality Suite**:
   - `pytest -q` (all tests pass).
   - `coverage report --fail-under=80` (global coverage $\ge 80\%$).
   - `coverage report --include=... --fail-under=95` (critical coverage $\ge 95\%$).
   - `ruff check .` (0 errors).
   - `mypy ...` (0 errors in 85+ files).
   - `pyright` (0 errors).
   - `compileall` (clean compilation).
   - `pip-audit` (0 CVEs).
   - `frontend` build (`npm run build` succeeds).
