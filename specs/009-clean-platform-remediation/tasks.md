# Tasks: Clean Platform Audit Remediation & PIT Identity Hardening

## Phase 1: Setup & Porting Baseline

**Purpose**: Establish clean baseline on `codex/platform-audit-remediation-clean` and document porting inventory.

- [ ] T001 Verify clean branch and remote HEADs on `codex/platform-audit-remediation-clean`
- [ ] T002 Update dependency manifests with cryptography and parser dependencies in requirements.txt and requirements.lock
- [ ] T003 [P] Add binary/artifact exclusion rules in .gitignore
- [ ] T004 Generate porting inventory report in reports/platform_audit_remediation_porting_inventory.md

---

## Phase 2: Foundational Infrastructure

**Purpose**: Core configuration and test harness foundations.

- [ ] T005 [P] Add trusted approval issuer configuration and keys in config/trusted_issuers.yaml
- [ ] T006 Reconcile canonical risk policy hash in config/risk_policy.yaml and run_pipeline.py

---

## Phase 3: User Story 1 - Risk Headroom & Cryptographic Approval Authenticity (Priority: P1) 🎯 MVP

**Goal**: Sizing headroom capping for same-direction position top-ups, Ed25519 digital signature verification for external approvals, and strict 9-field binding at `assert_paper_authorized()`.

**Independent Test**: `python -m pytest tests/test_risk_sizing_regression.py tests/test_approval_regression.py -vv`

### Implementation for User Story 1

- [ ] T007 [P] [US1] Implement headroom capping for same-direction top-ups in risk/validators.py
- [ ] T008 [P] [US1] Add regression tests for position sizing headroom, reversal, and risk reduction in tests/test_risk_sizing_regression.py
- [ ] T009 [US1] Implement Ed25519 signature creation and verification with canonical payload hashing in trading_stack/approval.py
- [ ] T010 [US1] Bind all 9 execution context fields with fail-closed resolution in PromotionEngine.assert_paper_authorized in orchestration/promotion.py
- [ ] T011 [US1] Add regression tests for stage, code_sha, evidence_hash, scope, subject_type, key_id, tamper, and expiry in tests/test_approval_regression.py
- [ ] T012 [US1] Document approval security remediation in reports/external_approval_security_remediation.md

---

## Phase 4: User Story 2 - PIT Temporal Identity & Date-Valid Alias Joins (Priority: P2)

**Goal**: Temporal bounds on security-master snapshots, date-valid alias joins, and AMTEKAUTO zero-length interval resolution.

**Independent Test**: `python -m pytest tests/test_pit_identity_regression.py tests/test_pit_candle_join.py -vv`

### Implementation for User Story 2

- [ ] T013 [P] [US2] Enforce valid_from < valid_until on aliases and snapshot limits on historical validity in tools/nifty200_pit/instrument_resolver.py
- [ ] T014 [P] [US2] Enforce date-bounded alias matching in research candle joins in trading_stack/datasets.py
- [ ] T015 [US2] Diagnose root cause of AMTEKAUTO zero-length interval in tools/nifty200_pit/intervals.py and fix interval generation
- [ ] T016 [US2] Rebuild PIT package using existing evidence only into a disposable path
- [ ] T017 [US2] Add regression tests for snapshot backdating, inverted alias, date-valid alias candle join, and AMTEKAUTO in tests/test_pit_candle_join.py and tests/test_pit_identity_regression.py
- [ ] T018 [US2] Document AMTEKAUTO interval root cause analysis in reports/nifty200_pit_amtekauto_interval_rca.md
- [ ] T019 [US2] Document 147 vs 200 diagnostic anchor decomposition in reports/nifty200_pit_diagnostic_anchor_delta.md

---

## Phase 5: User Story 3 - Platform Hardening, Storage Resilience & Analytics (Priority: P3)

**Goal**: Atomic migrations, backup quiescence, clean_db safety, classified provider fallback, calendar scheduler, AI liquidity, and dashboard compounding.

**Independent Test**: `python -m pytest tests/test_migration_atomicity.py tests/test_clean_db.py tests/test_scheduler.py tests/test_ai_risk_regression.py tests/test_dashboard_api.py -vv`

### Implementation for User Story 3

- [ ] T020 [P] [US3] Wrap migration SQL and schema_migrations insert in single atomic transaction in storage/migrations/runner.py
- [ ] T021 [P] [US3] Add backup safety, quiescence, and clean_db confirmation guards in operations/backup.py and clean_db.py
- [ ] T022 [P] [US3] Add classified provider fallback and exchange-session scheduling in data_platform/providers.py and scheduler.py
- [ ] T023 [P] [US3] Implement cooperative cancellation in orchestration/engine.py
- [ ] T024 [P] [US3] Ground AI liquidity in market candle volume and turnover in ai_research/workflow.py
- [ ] T025 [P] [US3] Fix monthly boundary compounding and zero-loss profit factor in tools/dashboard/api/main.py and tools/dashboard/ui/src/components/AnalyticsTab.tsx
- [ ] T026 [US3] Add regression tests for migration atomicity, backup safety, clean_db, scheduler, cooperative cancellation, AI risk, and dashboard analytics

---

## Phase 6: User Story 4 - Campaign 1 Governance & Reproducibility (Priority: P4)

**Goal**: Campaign 1 full ExperimentFamilySpec validation, structural importer validation flag, and static analysis cleanliness.

**Independent Test**: `python -m pytest tests/test_campaign1_governance.py -vv`

### Implementation for User Story 4

- [ ] T027 [P] [US4] Enforce full ExperimentFamilySpec definition hash validation in research.py
- [ ] T028 [P] [US4] Add structural validation only mode (--validate-structure-only) in tools/import_nifty200_pit.py
- [ ] T029 [US4] Add regression tests for Campaign 1 family immutability in tests/test_campaign1_governance.py
- [ ] T030 [US4] Ensure Pyright, Mypy, and Ruff configuration covers all modified files without errors

---

## Phase 7: Polish & Comprehensive Verification

**Purpose**: End-to-end multi-tool verification, fresh isolated worktree validation, clean Git status, push branch, and open PR.

- [ ] T031 Run focused test suite across all remediated modules
- [ ] T032 Run Ruff linter and format checker (`ruff check .`)
- [ ] T033 Run Mypy type checker across all specified modules
- [ ] T034 Run Pyright static analyzer
- [ ] T035 Run compileall across all core and test directories
- [ ] T036 Run git diff --check to verify no whitespace/conflict markers
- [ ] T037 Run full pytest test suite
- [ ] T038 Verify clean build in fresh isolated worktree
- [ ] T039 Review git diff against origin/main to ensure 0 tracked binary/parquet files and 0 secret keys
- [ ] T040 Push codex/platform-audit-remediation-clean and open PR to main with required description
- [ ] T041 Monitor GitHub Actions CI matrix runs to green completion
