# Implementation Plan: Platform Correctness, Safety, PIT Identity & Governance Remediation

**Branch**: `009-platform-audit-remediation` | **Date**: 2026-09-18 | **Spec**: [spec.md](file:///C:/Python%20projects/algo%20trading/specs/009-platform-audit-remediation/spec.md)

**Input**: Feature specification from `/specs/009-platform-audit-remediation/spec.md`

## Summary

Systematically remediate verified platform defects across 6 phases:
1. **Trading & Risk Correctness**: Fix position sizing top-up caps, stage-bounded approval verification, historical identity snapshot boundaries, alias interval ordering, and AI research market-liquidity inputs.
2. **Operational Hardening**: Wrap database migrations in transactions, harden backup/restore against WAL and concurrency issues, secure `clean_db.py`, fix provider error classification, derive schedule from market calendars, implement cooperative task cancellation, and fix dashboard boundary returns and stale responses.
3. **PIT Accounting & Provenance**: Generate persistent observation IDs, clarify redundant workbook observation reporting vs real gap accounting, and eliminate unconditional calendar blocker injections.
4. **Historical Evidence Closure**: Audit free public sources for 2012 anchor and missing monthly checkpoints.
5. **Campaign Governance**: Preserve and finalize Campaign 1 immutable family validation and reconcile canonical risk policy hashes.
6. **Reproducibility & Quality**: Update `requirements.txt` and `requirements.lock` with `xlrd`, align Pyright and coverage scopes, and verify zero regressions across the test suite.

## Technical Context

**Language/Version**: Python 3.12+ (tested on Python 3.12 and 3.13)
**Primary Dependencies**: DuckDB, pandas, pydantic, FastAPI, pytest, ruff, mypy, pyright
**Storage**: DuckDB (`market_data.duckdb` for runtime, `:memory:` / temp files for testing)
**Testing**: `pytest`
**Target Platform**: Windows 11 / Linux (Ubuntu CI)
**Constraints**: Zero network calls in tests; DuckDB single-writer constraint; fail-closed risk controls; preserve all uncommitted governance work.

## Constitution Check

- **I. Data Integrity & Validation**: PASS. Dropping invalid candles/intervals with explicit warnings; validating all alias intervals strictly.
- **II. Event-Driven Execution**: PASS. Preserved.
- **III. Concurrency & Thread Safety**: PASS. Cooperative thread cancellation and proper connection locking for backups.
- **IV. DuckDB Resiliency**: PASS. Single-writer lock respected; atomic migration transactions; WAL isolation on restore.
- **V. Cost Accuracy & Risk Limits**: PASS. Sizing limits strictly enforced on top-ups and reversals.

## Implementation Phases

- **Phase 1**: Reproduce code defects with regression tests; implement fixes in `risk/validators.py`, `trading_stack/approval.py`, `tools/nifty200_pit/`, `trading_stack/datasets.py`, and `ai_research/workflow.py`.
- **Phase 2**: Operational fixes in `storage/migrations/runner.py`, `operations/backup.py`, `clean_db.py`, `data_platform/providers.py`, `scheduler.py`, `orchestration/engine.py`, and dashboard API/UI.
- **Phase 3**: PIT reporting, observation IDs, and blocker accounting repairs.
- **Phase 4**: Evidence audit and closure pathways.
- **Phase 5**: Campaign governance reconciliation.
- **Phase 6**: Dependencies, CI configuration, and full verification.
