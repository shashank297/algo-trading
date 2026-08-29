# Phase 2.6 Final Forensic Remediation & Certification Tasks

- [x] R001 Update Phase 2.6 specifications, plan, data models, contracts, and quality checklists for forensic correctness.
- [x] R002 Remediate `experiments/statistical_tests.py` (DSR provenance separation with `TrialCountSource`, pure `compute_dsr_statistic`, bootstrap trade-expectancy resampling directly from trade PnLs with `ExpectancyBasis`, capital ruin direct simulation).
- [x] R003 Remediate `experiments/robustness.py` (`NestedWalkForwardSplitter` purge window exhaustion fail-closed with `PURGE_WINDOW_EXHAUSTS_TRAIN`/`VALIDATION`, full fold dataset lineage binding `dataset_snapshot_ids` and `dataset_content_hashes`, evidence-based cost and execution stress testing with `status` and `reason`).
- [x] R004 Update mathematical and adversarial unit tests in `tests/test_statistical_tests.py` (DSR spoofing prevention, trade expectancy units independence).
- [x] R005 Update integration, purge exhaustion, fold dataset lineage, real trial ID linkage, and evidence-based stress tests in `tests/test_robustness.py`.
- [x] R006 Execute full local verification matrix (pytest, Ruff, Mypy, Pyright, coverage $\ge 95\%$ on Phase 2.6, pip-audit).
- [ ] R007 Push branch `phase2.6-final-certification`, open PR to `main`, wait for all 6 required CI status checks to pass, and merge through protected branch rules.
- [ ] R008 Fetch merged `main`, verify exact-main CI, re-read remote implementation, and generate final certification report.



