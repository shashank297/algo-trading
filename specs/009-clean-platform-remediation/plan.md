# Implementation Plan: Clean Platform Audit Remediation & PIT Identity Hardening

**Branch**: `codex/platform-audit-remediation-clean` | **Date**: 2026-09-18 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/009-clean-platform-remediation/spec.md`

## Summary

Port verified software fixes from `009-platform-audit-remediation` and PR #27 onto a clean branch rooted at `origin/main` (`a8f383149187b8d0bbfb23253ba81c464ec8563f`). Close the remaining software defects: implement Ed25519 cryptographic authenticity and all 9 required execution bindings for `PromotionEngine.assert_paper_authorized()`; implement date-valid historical alias matching in research candle joins; diagnose and resolve the AMTEKAUTO zero-length constituent interval defect; document the 147 vs 200 diagnostic anchor delta; rebuild the PIT package using existing evidence only; and ensure all CI static analysis and regression test suites pass green.

## Technical Context

**Language/Version**: Python 3.12+ (tested across Python 3.12, Python 3.13 on Linux & Windows)

**Primary Dependencies**: `cryptography>=43.0.0`, `duckdb>=1.0.0`, `pandas>=2.2.0`, `pydantic>=2.7.0`, `pyyaml>=6.0.1`, `xlrd>=2.0.1`, `pypdf>=4.0.0`

**Storage**: DuckDB (`market_data.duckdb` isolated in test runs), Parquet, CSV

**Testing**: `pytest` (`tests/test_*.py`), deterministic unit and integration test fixtures

**Target Platform**: Windows (developer), Linux x86_64 (CI runners)

**Project Type**: Algorithmic trading research & execution platform

**Performance Goals**: Sub-second risk validation, deterministic backtest replay, <30s PIT dataset rebuild

**Constraints**: DuckDB single-writer concurrency; strict fail-closed governance (`approved_for_import = false`, `Independent QA = NOT_ASSERTED`, `Campaign Stage A = BLOCKED`, live trading disabled); zero untracked binary/Parquet bloat in PR; 100% clean CI (Ruff, Mypy, Pyright).

**Scale/Scope**: ~15 production modules affected, ~35 targeted regression tests, 4 detailed audit reports.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Data Integrity & Validation**: PASS. Inverted alias intervals and zero-length intervals are rejected.
- **Event-Driven Execution**: PASS. Preserved throughout trading stack.
- **Concurrency & Thread Safety**: PASS. Database transactions atomic, backup quiescence enforced.
- **DuckDB Resiliency**: PASS. Single-writer file lock honored; isolated temp databases used for rebuilds and tests.
- **Cost Accuracy & Risk Limits**: PASS. Sizing headroom validator caps risk-increasing top-ups.
- **Security & Data Safety**: PASS. No real secrets or private signing keys committed; Ed25519 verification uses public keys only. Live routing disabled.

## Project Structure

### Documentation (this feature)

```text
specs/009-clean-platform-remediation/
├── plan.md              # Implementation plan
├── research.md          # Phase 0 research & architectural decisions
├── data-model.md        # Phase 1 data entities and schemas
├── quickstart.md        # Phase 1 verification and run guide
├── contracts/
│   └── approval_contract.md # Cryptographic approval contract
└── tasks.md             # Execution task list
```

### Source Code (repository root)

```text
ai_research/
└── workflow.py          # Ground AI liquidity in market candle volume/turnover
config/
├── risk_policy.yaml     # Canonical risk policy with verifiable hash
└── trusted_issuers.yaml # Public keys for trusted approval issuers
data_platform/
├── providers.py         # Classified provider fallback
└── ...
orchestration/
├── engine.py            # Cooperative cancellation & scheduler hooks
└── promotion.py         # assert_paper_authorized() binding all 9 fields
reports/
├── external_approval_security_remediation.md
├── nifty200_pit_amtekauto_interval_rca.md
├── nifty200_pit_diagnostic_anchor_delta.md
└── platform_audit_remediation_porting_inventory.md
risk/
└── validators.py        # Available headroom capping on same-direction top-ups
storage/
├── migrations/runner.py # Atomic transaction wrapping DDL + schema_migrations
└── operations/backup.py # Backup quiescence and file safety
tools/
├── clean_db.py          # Confirmation and dry-run safety
├── import_nifty200_pit.py # Structure-only validation flag
└── nifty200_pit/
    ├── intervals.py     # Prevent zero-length intervals
    └── resolver.py      # Historical snapshot bounds and date-valid alias intervals
trading_stack/
├── approval.py          # Ed25519 signature verification & canonical payload hashing
└── datasets.py          # Date-bounded alias matching for historical candle joins
tests/
└── test_*.py            # Comprehensive regression suite
```

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Adding `cryptography` dependency | Secure Ed25519 asymmetric signature verification for external approvals | Plain string allowlists or shared HMAC secrets cannot prevent insider forgery or provide asymmetric non-repudiation |
