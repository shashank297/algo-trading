# Phase 2.6 Remediation Tasks

- [x] R001 Update Phase 2.6 specifications, plan, data models, contracts, and quality checklists for forensic correctness.
- [x] R002 Remediate `experiments/statistical_tests.py` (DSR fail-closed without authoritative family, real trial multiplicity $N$, capital ruin direct simulation, bootstrap expectancy).
- [x] R003 Remediate `experiments/robustness.py` (`NestedWalkForwardSplitter` single authoritative splitter with dual-boundary purge and post-test embargo, real `selected_trial_id` mapping, parameter robustness with plateau fraction and rank stability, cost stress with slippage/liquidity, execution stress with reduced liquidity, OOS-only stress evidence, and comprehensive evidence hash binding).
- [x] R004 Update mathematical and adversarial unit tests in `tests/test_statistical_tests.py`.
- [x] R005 Update integration, dual purge/embargo, plateau robustness, real trial ID linkage, and stress tests in `tests/test_robustness.py`.
- [x] R006 Execute full local verification matrix (pytest, Ruff, Mypy, Pyright, coverage $\ge 95\%$ on Phase 2.6, pip-audit).
- [ ] R007 Push branch `phase2.6-remediation`, open PR to `main`, wait for all 6 required CI status checks to pass, and merge through protected branch rules.
- [ ] R008 Fetch merged `main`, verify exact-main CI, re-read remote implementation, and generate final certification report.


