# Phase 2.2 Tasks

## Phase 1: Setup & Migration

- [x] T001 Create `specs/phase2/2.2-certified-multitimeframe-data/` spec directory (already done)
- [x] T002 Create `storage/migrations/016_derived_datasets.sql` with `derived_datasets` and `cross_provider_reconciliations` tables

## Phase 2: Foundational — Core Resampling Engine

- [x] T003 [US1] Create `data_platform/resampling.py` with `ResampledBar`, `DerivedDatasetCertification`, and `SessionBarResampler` class implementing session-aware 1m→Nm OHLCV derivation
- [x] T004 [US1] Implement rejection guards in `SessionBarResampler`: mixed basis, mixed symbol/exchange, quarantined intervals, unsupported timeframes
- [x] T005 [US1] Implement `derive_and_certify()` method that computes content_hash, runs DQ, and persists lineage

## Phase 3: DQ Certification

- [x] T006 [US3] Create `data_platform/dq_derived.py` with `DerivedDQReport` dataclass and `DerivedBarDQCertifier` class implementing all 6 DQ checks (schema, OHLC integrity, duplicates, session alignment, missing buckets, timestamp monotonicity)

## Phase 4: Lineage Registry — DuckDB

- [x] T007 [US2] [P] Add `persist_derived_dataset()`, `get_derived_datasets()`, `get_canonical_1m_bars()` methods to `storage/duckdb_manager.py`
- [x] T008 [US5] [P] Add `persist_reconciliation()`, `get_reconciliations()` methods to `storage/duckdb_manager.py`

## Phase 5: Cross-Provider Verification

- [x] T009 [US5] Create `data_platform/provider_verification.py` with `ProviderReconciliationResult`, `VerificationSeverity`, `BarComparisonOutcome`, `ProviderVerificationReport`, and `CrossProviderVerifier` class
- [x] T010 [US5] Implement `CrossProviderVerifier.verify()` with tolerance-based bar comparison, DISAGREMENT→DATA_VERIFICATION_WARNING, and persistence to `cross_provider_reconciliations`
- [x] T011 [US5] Implement the no-blending invariant: verify that provider disagreements never produce averaged/synthetic values

## Phase 6: Public API Export

- [x] T012 [P] Update `data_platform/__init__.py` to export `SessionBarResampler`, `DerivedDatasetCertification`, `CrossProviderVerifier`, `ProviderVerificationReport`, `VerificationSeverity`

## Phase 7: CLI Integration

- [x] T013 [US6] Add `--source-dataset`, `--derived-timeframe`, `--primary-provider`, `--secondary-provider`, `--verification-severity`, `--start-date`, `--end-date` arguments to `research.py`
- [x] T014 [US6] Implement `build-derived-bars` command handler in `research.py`: load canonical 1m bars, call `SessionBarResampler.derive_and_certify()`, print lineage + certification status, exit non-zero on DQ failure
- [x] T015 [US6] Implement `verify-market-provider` command handler in `research.py`: load primary and secondary bars, call `CrossProviderVerifier.verify()`, print reconciliation summary

## Phase 8: Tests

- [x] T016 [P] [US1] Create `tests/test_resampling.py` — test correct 1m→5m OHLCV aggregation (open=first, high=max, low=min, close=last, volume=sum)
- [x] T017 [P] [US1] Add test 1m→15m correct aggregation
- [x] T018 [P] [US1] Add test 1m→30m correct aggregation
- [x] T019 [P] [US1] Add test 1m→60m correct aggregation
- [x] T020 [P] [US1] Add test session boundary enforcement (bars after 15:30 IST excluded)
- [x] T021 [P] [US1] Add test market holiday produces zero bars
- [x] T022 [P] [US1] Add test special session (shortened) produces bars only within short window
- [x] T023 [P] [US1] Add test missing minute in session: bucket with gap still produces correct aggregate with available bars
- [x] T024 [P] [US1] Add test quarantined minute rejection: raises error when quarantined flag present
- [x] T025 [P] [US1] Add test incomplete last bucket is dropped (trailing partial bucket not emitted)
- [x] T026 [P] [US1] Add test mixed adjustment basis rejection
- [x] T027 [P] [US4] Add test deterministic hash: same source → same content_hash
- [x] T028 [P] [US4] Add test source mutation changes derived hash
- [x] T029 [P] [US1] Add test no future/incomplete bar leakage (bars timestamped after session close are not included)
- [x] T030 [P] [US5] Create `tests/test_provider_verification.py` — test exact provider match (all MATCH)
- [x] T031 [P] [US5] Add test tolerance match (price within tolerance → TOLERANCE_MATCH)
- [x] T032 [P] [US5] Add test provider disagreement (price beyond tolerance → DISAGREEMENT + warning)
- [x] T033 [P] [US5] Add test unavailable secondary bar (missing from secondary → UNAVAILABLE)
- [x] T034 [P] [US5] Add test no provider blending: verify primary bars are never modified by verification
- [x] T035 [P] [US2] Create `tests/test_migration_016.py` — test clean DB migration creates both tables
- [x] T036 [P] [US2] Add test incremental upgrade migration preserves existing data

## Phase 9: Documentation

- [x] T037 [P] Create `docs/derived_bars.md` with operator guide for derivation, DQ certification, and cross-provider verification

## Phase 10: Polish & Final Verification

- [ ] T038 Run `.\venv\Scripts\ruff.exe check .` and fix any issues
- [ ] T039 Run `.\venv\Scripts\mypy.exe data_platform storage research.py` and fix any type errors
- [ ] T040 Run `.\venv\Scripts\python.exe -m pytest -q` and verify full suite (428+ passed, all Phase 2.2 tests pass)
- [ ] T041 Push `phase2/2.2-certified-multitimeframe-data` branch and confirm CI green on exact SHA

## Phase 11: Fail-Closed Remediation

- [x] T042 Require source dataset identity, canonical lifecycle, immutable hash, and hash-bound DQ evidence before governed derivation.
- [x] T043 Require exact consecutive source minutes; persist `DQ_FAILED` forensic evidence before raising.
- [x] T044 Atomically admit certified derived candles, lineage, `market_datasets`, and authoritative DQ evidence.
- [x] T045 Bind provider verification to explicit dataset identities and persist BLOCKING reports before raising.
- [x] T046 Apply inclusive local-date CLI ranges and document `--timeframe` as the target timeframe.
- [ ] T047 Complete full local and exact-SHA GitHub Actions verification before certifying this phase.

## Dependencies

- T003, T004, T005 depend on T002 (migration must exist before DuckDB calls)
- T006 depends on T003 (DQ certifier validates resampled output)
- T005 depends on T006 (derive_and_certify runs DQ before persisting)
- T007, T008 depend on T002 (new tables must exist)
- T009, T010, T011 depend on T008
- T012 depends on T003, T005, T009
- T013, T014 depends on T003, T005, T006, T007, T012
- T015 depends on T009, T010, T011, T008
- T016–T029 depend on T003, T004, T005, T006
- T030–T034 depend on T009, T010, T011
- T035–T036 depend on T002
- T038–T041 depend on T037 (all implementation complete)
