# Phase 2.6 Final Forensic Remediation & Certification Tasks

- [x] R001 Update Phase 2.6 specifications, plan, data models, contracts, and quality checklists for forensic correctness.
- [x] R002 Remediate `experiments/statistical_tests.py` (DSR storage-backed database verification with `TrialCountSource`, pure `compute_dsr_statistic`, `resolve_authoritative_dsr`, bootstrap trade-expectancy resampling directly from trade PnLs with `ExpectancyBasis`, capital ruin direct simulation).
- [x] R003 Remediate `experiments/robustness.py` (`NestedWalkForwardSplitter` purge window exhaustion fail-closed with `PURGE_WINDOW_EXHAUSTS_TRAIN`/`VALIDATION`, full fold dataset lineage binding `dataset_snapshot_ids` and `dataset_content_hashes`, evidence-based cost and execution stress testing without synthetic proxies).
- [x] R004 Update mathematical and adversarial unit tests in `tests/test_statistical_tests.py` (DSR database backing and spoofing prevention, trade expectancy units independence).
- [x] R005 Update integration, purge exhaustion, fold dataset lineage, real trial ID linkage, and evidence-based stress tests in `tests/test_robustness.py`.
- [x] R006 Execute full local verification matrix (pytest, compileall, coverage on Phase 2.6).
- [x] R007 Push branch `phase2.6-final-certification`, open PR to `main`, wait for all 6 required CI status checks to pass, and merge through protected branch rules (PR #9 merged).
- [x] R008 Fetch merged `main`, verify exact-main CI (CI run #102 green), and generate final certification report.



