# Tasks: NIFTY-200 PIT Evidence Resolution & Forensic Gap Audit

## Phase 1: Setup & Baseline Analysis

- [x] T001 Audit existing blocker ledger (`artifacts/nifty200_pit_v1/blocker_ledger.csv`), unresolved gaps (`unresolved_gaps.csv`), validation report (`validation_report.json`), aliases, master, and monthly gap analysis.
- [x] T002 Verify git status, existing working tree modifications, and verify no modifications are lost.

---

## Phase 2: Authoritative Evidence Searches & Probing

- [x] T003 Probe official Nifty Indices archive API (`/reports/historical-data/Index/`) for all report types across 2011, 2012, and 2013 to establish availability boundary of Report Type 4.
- [x] T004 Probe official Nifty Indices monthly weightage ZIP downloads (`indices_data<Mon><YYYY>.zip`) from 2022-04 through 2026-08, download representative samples (`Apr2022`, `Aug2026`), and inspect internal archive namelists to verify publisher omission of NIFTY 200.
- [x] T005 Probe NSE archives and Nifty Indices press release candidate repository (`data/raw/nifty200_pit_public_sources/press_releases/candidates/`) including `ind_prs18072011.pdf` and circular records for dated 2012-01-02 200-member constituent proof.
- [x] T006 Audit `IndexInclExcl.xls` ('Nifty 200' sheet) and B1 challenger dataset (`deshpanda_nse_screener_reconstitution_events.parquet`) against platform non-inference and governance rules (Rules 4-10).

---

## Phase 3: Exact Forensic Evidence-Gap Report & Documentation

- [x] T007 Generate exact, comprehensive final evidence-gap report in `reports/nifty200_pit_evidence_gap_report_20260918.md` covering all 1,121 blockers across the 4 blocker categories.
- [x] T008 Update `.specify/feature.json` to register feature 010.

---

## Phase 4: Multi-Tool Verification & Safety Assertion

- [x] T009 Run pytest on focused PIT test suite (`tests/test_nifty200_pit_*.py -vv`).
- [x] T010 Run pytest on storage resilience test suite (`tests/test_storage*.py -vv`).
- [x] T011 Run Ruff linter (`ruff check .`).
- [x] T012 Run Mypy type checker across `ai_research/ tools/ data_platform/ storage/`.
- [x] T013 Run Pyright static analysis.
- [x] T014 Run compileall across all specified packages.
- [x] T015 Run `git diff --check`.
- [x] T016 Run dry-run importer (`tools/import_nifty200_pit.py --dry-run`) and assert `market_data.duckdb` and `market_data.duckdb.wal` remain untouched.
- [x] T017 Confirm final governance status strings:
  - `NIFTY-200 PIT RECONSTRUCTION: DATA EVIDENCE BLOCKED`
  - `INDEPENDENT QA: NOT ASSERTED`
  - `CAMPAIGN STAGE A: BLOCKED`
