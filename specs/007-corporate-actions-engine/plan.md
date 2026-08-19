# Implementation Plan: Institutional Corporate Actions & Total Return Engine

**Branch**: `007-corporate-actions-engine` | **Date**: 2026-08-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-corporate-actions-engine/spec.md`

## Summary

Implement an institutional-grade corporate actions foundation for Indian equities (NSE):
1. Support four explicit adjustment modes: `UNADJUSTED`, `SPLIT_ADJUSTED`, `BACK_ADJUSTED`, and `TOTAL_RETURN`.
2. Standardize on `share_multiplier` ($R = \text{shares\_after} / \text{shares\_before}$) with correct bonus ratio parsing (`Bonus N:M` $\to (M+N)/M$).
3. Redesign the database schema with unique `action_id` primary keys and full corporate action lineage.
4. Enforce strict `Asia/Kolkata` trading session date evaluation and previous active session close ($P_{\text{prev}}$) lookup.
5. Guarantee turnover invariance ($P \times V = \text{invariant}$) and protect against double-adjustment bugs.
6. Provide a separate `TotalReturnEngine` for exact dividend-reinvested series ($\text{TRI}_t = \text{TRI}_{t-1} \times (1 + r_t^{\text{TR}})$).

## Technical Context

**Language/Version**: Python 3.12+ / 3.13
**Primary Dependencies**: DuckDB, pandas, numpy, pydantic, loguru
**Storage**: DuckDB (`market_data.duckdb`)
**Testing**: pytest (`tests/`)
**Target Platform**: Windows / Linux
**Project Type**: Quantitative Trading Research Platform

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Data Integrity & Validation**: PASS. Raw `historical_candles` remains unadjusted. Adjustments are applied deterministically via transformations.
- **II. Event-Driven Execution**: PASS. Causal order replay is preserved.
- **III. Concurrency & Thread Safety**: PASS. Database writes and cache access maintain write locks.
- **IV. DuckDB Resiliency**: PASS. Retries and transactional safety maintained.
- **V. Cost Accuracy & Risk Limits**: PASS. Traded turnover and cost models remain exact.

## Project Structure

### Documentation (this feature)

```text
specs/007-corporate-actions-engine/
├── plan.md              # This file
├── research.md          # Mathematical formulas and architectural decisions
├── data-model.md        # Database schema and Enum definitions
├── quickstart.md        # Verification and property-based test procedures
└── tasks.md             # Implementation checklist (/speckit-tasks output)
```

### Source Code (repository root)

```text
data_platform/
├── contracts.py         # PriceAdjustment enum (UNADJUSTED, SPLIT_ADJUSTED, BACK_ADJUSTED, TOTAL_RETURN)
└── adjustments.py       # PriceAdjustmentEngine & TotalReturnEngine

storage/
├── duckdb_manager.py    # corporate_actions CRUD with action_id and share_multiplier
└── database_schema.sql  # Refined corporate_actions table schema

data/
└── corporate_actions_nifty200.json # Updated seed fixture with share_multiplier and action_id

tools/
└── import_corporate_actions.py     # Corporate actions normalizer and importer

trading_stack/
├── datasets.py          # Panel builder using PriceAdjustment enum
└── pipeline.py          # Strongly typed pipeline runner
```
