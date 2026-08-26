# Implementation Plan: Final Audit Remediation & Institutional Hardening

**Directory**: `specs/008-final-audit-remediation` | **Date**: 2026-08-26 | **Spec**: [spec.md](./spec.md)

## Summary

Remediate all open audit findings across P0-3, P1-9, E-8, E-10, and E-12, while fixing vectorized transaction cost application and single-asset paper sizing/risk estimation. The implementation establishes exact immutable lineage binding, strict receipt-time causality in forward paper execution, resilient stream recovery with closed interval tracking, atomic multi-category certification, and >=95% code coverage across all critical modules.

## Technical Context

- **Language/Version**: Python 3.12+ (tested on Python 3.12 and 3.13)
- **Primary Dependencies**: DuckDB, Pandas, NumPy, Loguru, Pydantic/dataclasses, Pytest, Uvicorn, FastAPI
- **Storage**: DuckDB (`market_data.duckdb`) single-writer with SQL migration engine (`storage/migrations/*.sql`)
- **Testing**: `pytest`, `pytest-cov`, `coverage`
- **Target Platform**: Windows / Linux
- **Project Type**: Quantitative Research & Algorithmic Trading Platform
- **Performance Goals**: Zero lookahead bias, deterministic reproducibility, 0 type/lint violations

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

1. **I. Data Integrity & Validation**: PASS — Exact DQ lineage binds every research frame to 6 zero-issue checks; corrupt or uncertified rows fail closed.
2. **II. Event-Driven Execution**: PASS — `EventDrivenBacktester` and `ForwardPaperSessionEngine` enforce strict causal execution.
3. **III. Concurrency & Thread Safety**: PASS — DuckDB writes synchronized via `_write_lock`, thread pools isolated.
4. **IV. DuckDB Resiliency**: PASS — Migrations are versioned and checksum-validated; read paths connect with `read_only=True`.
5. **V. Cost Accuracy & Risk Limits**: PASS — Indian delivery cost schedules applied across all execution modes including vectorized.

## Project Structure

### Documentation (this feature)

```text
specs/008-final-audit-remediation/
├── plan.md              # Implementation plan
├── research.md          # Technical research & decisions
├── data-model.md        # Entities, state machines & schemas
├── quickstart.md        # Verification guide & runbook
├── contracts/           # Interface contracts & API schemas
└── tasks.md             # Actionable dependency-ordered tasks
```

### Source Code Components

```text
data_platform/
├── contracts.py                 # Core domain dataclasses & adjustments
├── live_admission.py           # Live market data admission validator
└── service.py                  # Forensic dataset intake and promotion gateway

smartapi/
└── websocket_client.py         # SmartAPI WebSocket 2.0 streaming client with gap recovery

storage/
├── duckdb_manager.py           # Persistence layer and transactional queries
└── migrations/                 # Schema migration runner and versioned SQL scripts
    ├── 007_quality_report_dataset_id.sql
    ├── 008_market_datasets_alignment.sql
    ├── 009_raw_bar_observations_provider.sql
    └── 010_exact_frame_evidence_and_gap_recovery.sql

trading_stack/
├── backtest.py                 # Vectorized & event-driven backtesting engines
├── certification.py            # Run certification service (5-category audit)
├── datasets.py                 # Synchronized panel builder with exact evidence binding
├── domain.py                   # OpeningTickObservation and Bar domain models
├── live_aggregator.py          # Real-time bar aggregator with interval closure
├── paper.py                    # Single-asset forward paper engine
├── pipeline.py                 # Strategy execution and data loading pipeline
├── portfolio.py                # Multi-strategy portfolio rebalancing & allocation
├── portfolio_paper.py          # Portfolio forward paper session engine
├── promotion.py                # Promotion engine with stitched OOS return metrics
└── universe.py                 # PIT universe service and benchmark registry

tests/
├── test_causality_and_invariants.py
├── test_certification_coverage.py
├── test_multi_strategy_platform.py
├── test_stream_gap_recovery.py
└── test_critical_path_coverage.py
```
