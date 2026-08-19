# Implementation Plan: Platform Hardening & Ingestion Resilience

**Branch**: `006-platform-hardening-resilience` | **Date**: 2026-08-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-platform-hardening-resilience/spec.md`

## Summary

Harden the platform against race conditions, rate limit violations, and malformed API queries:
1. Introduce a synchronized `RateLimiter` sharing pattern across `HistoricalDataClient` workers in `tools/backfill_market_history.py`.
2. Fix `tools/dashboard/api/main.py:get_strategies` query to safely aggregate non-colon portfolio run IDs.
3. Update `tools/dashboard/ui/src/components/AnalyticsTab.tsx` to dynamically resolve `API_BASE`.
4. Add same-day local caching in `smartapi/instrument.py:download_instrument_master`.

## Technical Context

**Language/Version**: Python 3.12+, TypeScript / React 18
**Primary Dependencies**: FastAPI, DuckDB, requests, loguru, Pydantic, TailwindCSS/Lucide React
**Storage**: DuckDB (`market_data.duckdb`)
**Testing**: pytest (`tests/`)
**Target Platform**: Windows / Linux
**Project Type**: Systematic Trading CLI & Analytics Dashboard

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Data Integrity & Validation**: PASS. All changes maintain strict data validation and drop invalid bars gracefully.
- **II. Event-Driven Execution**: PASS. Preserves event-driven backtesting engine.
- **III. Concurrency & Thread Safety**: PASS. Centralizes and synchronizes broker rate limiting.
- **IV. DuckDB Resiliency**: PASS. Read-only queries maintain connection safety and TTL caching.
- **V. Cost Accuracy & Risk Limits**: PASS. No changes to execution costs or risk gates.

## Project Structure

### Documentation (this feature)

```text
specs/006-platform-hardening-resilience/
├── plan.md              # This file
├── research.md          # Technical decisions and rationale
├── data-model.md        # Updated interfaces and data contracts
├── quickstart.md        # Verification and smoke test instructions
└── tasks.md             # Implementation checklist (/speckit-tasks output)
```

### Source Code (repository root)

```text
smartapi/
├── historical.py        # Shared RateLimiter instance injection
└── instrument.py        # Same-day local disk caching

tools/
├── backfill_market_history.py # Shared rate limiter wiring across thread pool
└── dashboard/
    ├── api/
    │   └── main.py      # Fixed symbol extraction in get_strategies
    └── ui/src/components/
        └── AnalyticsTab.tsx # Dynamic API_BASE resolution
```
