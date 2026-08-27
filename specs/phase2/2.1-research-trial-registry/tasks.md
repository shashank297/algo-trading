# Tasks: Phase 2.1 — Immutable Research Trial Registry

## Phase 1: Database Migration & Storage APIs

- [x] **Task 1.1**: Verify and finalize `storage/migrations/014_research_trials.sql` schema (`experiment_families` and `research_trials_log` tables with index `idx_trials_family_status`).
- [x] **Task 1.2**: Implement and verify DuckDB storage methods in `storage/duckdb_manager.py`:
  - `register_experiment_family(family: ExperimentFamilySpec)` (with immutability check on definition hash)
  - `get_experiment_family(family_id: str) -> dict[str, Any] | None`
  - `list_experiment_families() -> list[dict[str, Any]]`
  - `create_research_trial(trial: ResearchTrial) -> str` (with atomic budget check)
  - `reserve_research_trial(trial: ResearchTrial) -> str`
  - `get_research_trial(trial_id: str) -> dict[str, Any] | None`
  - `find_exact_reusable_trial(family_id: str, ...)`
  - `list_research_trials(family_id: str | None = None, strategy: str | None = None, status: str | None = None) -> list[dict[str, Any]]`
  - `transition_research_trial(trial_id: str, status: str, *, metrics: dict[str, Any] | None = None, error_message: str | None = None, invalidation_reason: str | None = None)`
  - `mark_trial_selected(trial_id: str, selected: bool = True)`
  - `invalidate_trial(trial_id: str, reason: str)`
  - `remaining_trial_budget(family_id: str) -> int`
  - `research_trial_summary(family_id: str) -> dict[str, Any]`
  - `recover_interrupted_research_trials() -> int`

## Phase 2: Domain Models & Experiment Spec Contracts

- [x] **Task 2.1**: Finalize `experiments/trials.py` (`ExperimentFamilySpec`, `ResearchTrial`, `TrialStatus`, `canonical_hash`).
- [x] **Task 2.2**: Update `experiments/models.py` (`ExperimentSpec` and `MassExperimentSpec`) to accept `experiment_family_id: str | None = None`.
- [x] **Task 2.3**: Expose models cleanly in `experiments/__init__.py`.

## Phase 3: Manager & Evaluator Integrations

- [x] **Task 3.1**: Integrate `ExperimentManager` (`experiments/manager.py`):
  - In `run()` / `run_single()`: If `spec.experiment_family_id` is set, reserve trial slot before execution, persist as `RUNNING`, update to `SUCCEEDED` with metrics hash on success or `FAILED` on exception.
- [x] **Task 3.2**: Integrate `WalkForwardEvaluator` (`experiments/walk_forward.py`):
  - In candidate grid evaluation loop: reserve and persist `ResearchTrial` for EVERY evaluated candidate prior to `_run()`.
  - Fail closed if trial budget is exhausted before candidate evaluation.
  - Persist losing candidates with status `SUCCEEDED`.
  - Mark winning/best candidate with `selected = True`.
  - Persist failed candidates with status `FAILED` and error evidence.
- [x] **Task 3.3**: Integrate `MassExperimentManager` (`experiments/mass.py`):
  - Propagate `experiment_family_id` to child specs/jobs.
  - Ensure exact deterministic resume does not double-count research trials.

## Phase 4: Read-Only Research-Trials CLI

- [x] **Task 4.1**: Implement `--command research-trials` in `research.py`:
  - Support filters: `--experiment-family-id`, `--trial-id`, `--strategy`, `--status`.
  - Display family summaries (budget, consumed, remaining, status breakdown, selected count).
  - Display trial detail and trial list tables.
  - Enforce read-only semantics (no delete operations).

## Phase 5: Test Suite & Statistical Integrity Acceptance

- [x] **Task 5.1**: Create `tests/test_research_trials.py` covering:
  - Domain model validation & deterministic hashing.
  - Family definition immutability & budget immutability.
  - Lifecycle state transitions (`PLANNED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `INVALIDATED`, `CANCELLED`).
  - Pre-evaluation trial budget reservation & fail-closed $N+1$ blocking.
  - Concurrent budget race condition prevention under transactions.
  - Interrupted recovery (`RUNNING` -> `FAILED / INTERRUPTED_PROCESS`).
  - Forensic invalidation without deletion.
  - `ExperimentManager` integration (success & failure persistence).
  - `WalkForwardEvaluator` candidate retention (all candidates recorded, losing trials retained, winner marked selected).
  - `MassExperimentManager` family propagation & resume idempotency.
  - Read-only CLI output & filtering.
  - Statistical Integrity Acceptance test (20 candidates evaluated -> 20 persisted, 19 losing, 1 selected, 21st candidate blocked).
- [x] **Task 5.2**: Create `tests/test_migration_014.py` verifying fresh DB migration and 001-013 -> 014 upgrade.

## Phase 6: Documentation & Quality Verification

- [x] **Task 6.1**: Create `docs/research_trials.md` covering architecture, invariants, models, budget rules, lifecycle, CLI, and future DSR usage.
- [x] **Task 6.2**: Run full quality verification:
  - `pytest -q` (100% pass)
  - Global coverage $\ge 80\%$
  - Critical path coverage $\ge 95\%$
  - `ruff check .` (0 errors)
  - `mypy ...` (0 errors)
  - `pyright` (0 errors)
  - `compileall` (clean)
  - `pip-audit` (clean)
  - Frontend build (`npm run build` succeeds)

## Phase 7: Delivery

- [ ] **Task 7.1**: Commit changes (`feat(research): complete immutable research trial registry`).
- [ ] **Task 7.2**: Push branch `phase2/2.1-research-trial-registry` to origin.
- [ ] **Task 7.3**: Monitor and verify GitHub Actions CI on exact pushed SHA until 100% green.
