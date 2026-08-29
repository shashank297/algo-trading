# Phase 2.6 Tasks

- [x] T001 Define Phase 2.6 specification, plan, data models, contracts, and quickstart documentation.
- [x] T002 Implement pure statistical functions (PSR, DSR, bootstrap, Monte Carlo) in `experiments/statistical_tests.py`.
- [x] T003 Implement nested walk-forward, purge/embargo, parameter robustness selection, and stress testing in `experiments/robustness.py`.
- [x] T004 Add migration `022_phase2_6_robustness.sql` and immutable DuckDB persistence in `storage/duckdb_manager.py`.
- [x] T005 Integrate `RobustnessEvaluator` with `research.py` CLI, export public models in `experiments/__init__.py`, and add config defaults to `config/config.example.yaml`.
- [x] T006 Add unit and adversarial mathematical tests in `tests/test_statistical_tests.py`.
- [x] T007 Add integration, leakage-prevention, stress, trial-registry linkage, and persistence tests in `tests/test_robustness.py`.
- [x] T008 Update CI configuration in `.github/workflows/ci.yml` to include `experiments/robustness.py` and `experiments/statistical_tests.py` in critical coverage.
- [x] T009 Run the complete local verification matrix (pytest, Ruff, Mypy, Pyright, coverage, pip-audit).
- [x] T010 Commit Phase 2.6 implementation and push directly to `origin/main`, then verify exact-main CI.

