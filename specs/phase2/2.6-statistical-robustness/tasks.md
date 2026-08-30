# Phase 2.6 Final Forensic Remediation & Certification Tasks

- [x] R001 Update Phase 2.6 specifications, plan, data models, contracts, and quality checklists for forensic correctness.
- [x] R002 Remediate `experiments/statistical_tests.py` (DSR storage-backed database verification with `TrialCountSource`, pure `compute_dsr_statistic`, authoritative `resolve_authoritative_dsr` resolver as single authoritative DSR engine, anti-spoofing guarantees, bootstrap trade-expectancy resampling directly from trade PnLs with `ExpectancyBasis`, capital ruin direct simulation).
- [x] R003 Remediate `experiments/robustness.py` (`NestedWalkForwardSplitter` purge window exhaustion fail-closed with `PURGE_WINDOW_EXHAUSTS_TRAIN`/`VALIDATION`, full fold dataset lineage binding `dataset_snapshot_ids` and `dataset_content_hashes`, decoupled cost stress and execution stress, reduced liquidity fail-closed without 1,000,000 synthetic share fabrication, and direct delegation to `resolve_authoritative_dsr`).
- [x] R004 Update mathematical and adversarial unit tests in `tests/test_statistical_tests.py` (anti-spoofing guarantees ignoring caller Sharpes, DSR database backing, trade expectancy units independence).
- [x] R005 Update integration, purge exhaustion, fold dataset lineage, real trial ID linkage, participation rate, and fail-closed volume stress tests in `tests/test_robustness.py`.
- [x] R006 Execute full local verification matrix (pytest, compileall, coverage on Phase 2.6 >= 95%).
- [x] R007 Push branch `phase2.6-final-certification-remediation`, open PR to `main`, wait for all 6 required CI status checks to pass, and merge through protected branch rules (PR #11 merged).
- [x] R008 Push branch `phase2.6-closure-remediation` with non-finite (+Inf/-Inf) volume fail-closed validation and adversarial tests, open PR #12, merge to `main`, verify exact-main CI green, and persist `certification_report.md`.





