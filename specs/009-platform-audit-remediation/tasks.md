# Tasks: Platform Correctness, Safety, PIT Identity & Governance Remediation

**Feature**: `009-platform-audit-remediation`
**Spec**: [spec.md](file:///C:/Python%20projects/algo%20trading/specs/009-platform-audit-remediation/spec.md)
**Plan**: [plan.md](file:///C:/Python%20projects/algo%20trading/specs/009-platform-audit-remediation/plan.md)

---

## Phase 1: Setup & Regression Test Suite Creation

- [x] T001 [P] Create regression test for position sizing top-ups and reversals in `tests/test_risk_sizing_regression.py`
- [x] T002 [P] Create regression test for external approval verification in `tests/test_approval_regression.py`
- [x] T003 [P] Create regression test for historical identity and alias periods in `tests/test_pit_identity_regression.py`
- [x] T004 [P] Create regression test for database migration rollback in `tests/test_migration_atomicity.py`
- [x] T005 [P] Create regression test for AI research risk inputs in `tests/test_ai_risk_regression.py`

---

## Phase 2: User Story 1 - Risk & Approval Enforcement (Priority: P1)

- [x] T006 Fix position sizing cap logic in `risk/validators.py` for same-direction top-ups
- [x] T007 Fix external approval verification stage bounds and field validation in `trading_stack/approval.py`
- [x] T008 Fix AI research mark queries and market turnover calculation in `ai_research/workflow.py`
- [x] T009 Run regression tests for User Story 1: `pytest tests/test_risk_sizing_regression.py tests/test_approval_regression.py tests/test_ai_risk_regression.py`

---

## Phase 3: User Story 2 - PIT Identity, Aliases & Research Integration (Priority: P1)

- [x] T010 Fix listing date vs snapshot date in `tools/nifty200_pit/build_public_dataset.py` and `tools/nifty200_pit/instrument_resolver.py`
- [x] T011 Enforce `valid_from < valid_until` in alias generation in `tools/nifty200_pit/build_public_dataset.py`
- [x] T012 Integrate durable instrument IDs and aliases in `trading_stack/datasets.py` and `tools/import_nifty200_pit.py`
- [x] T013 Run regression tests for User Story 2: `pytest tests/test_pit_identity_regression.py`

---

## Phase 4: User Story 3 - Operational & Platform Hardening (Priority: P2)

- [x] T014 Enforce atomic transactions in `storage/migrations/runner.py`
- [x] T015 Secure backup and restore in `operations/backup.py` with WAL cleanup and writer quiescence
- [x] T016 Guard `clean_db.py` with explicit targets, dry-run, and transactional error handling
- [x] T017 Narrow provider fallback and verify adjustment metadata in `data_platform/providers.py`
- [x] T018 Derive scheduler triggers from market calendar in `scheduler.py`
- [x] T019 Implement cooperative cancellation in `orchestration/engine.py`
- [x] T020 Fix dashboard monthly boundary returns and profit factor in `tools/dashboard/api/main.py`
- [x] T021 Fix dashboard frontend error states and stale response handling in `tools/dashboard/ui/src/components/AnalyticsTab.tsx`
- [x] T022 Run regression tests for User Story 3: `pytest tests/test_migration_atomicity.py`

---

## Phase 5: User Story 4 - Governance & Reproducibility (Priority: P2)

- [x] T023 Reconcile Campaign 1 immutable family validation and risk policy hashes in `run_pipeline.py` and `config/risk_policy.yaml`
- [x] T024 Add `xlrd>=2.0.1` and `pypdf` to `requirements.txt` and `requirements.lock`
- [x] T025 Update `pyrightconfig.json` and CI workflow settings to cover all modules
- [x] T026 PIT lineage: stable observation IDs and clear disposition metrics in `tools/nifty200_pit/build_public_dataset.py`

---

## Phase 6: End-to-End Verification & Validation Dry-Run

- [x] T027 Run full pytest suite (all 927+ tests pass on main, all 998 tests pass in worktree)
- [x] T028 Run ruff check, mypy, pyright, and compileall (0 ruff errors, 0 pyright errors, clean compileall)
- [x] T029 Execute import dry-run verification (`tools/import_nifty200_pit.py --dry-run` and `--validate-structure-only`)
- [x] T030 Compile comprehensive verification report
