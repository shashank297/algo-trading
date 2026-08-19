# Implementation Tasks: Institutional Corporate Actions & Total Return Engine

**Feature**: `007-corporate-actions-engine`
**Branch**: `007-corporate-actions-engine`
**Specification**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

---

## Phase 1: Setup & Foundational Schema (Blocking Prerequisites)

**Purpose**: Establish four-mode `PriceAdjustment` contract, schema updates with `action_id`, and `share_multiplier` foundation.

- [x] T001 Update `PriceAdjustment` enum in `data_platform/contracts.py` to support `UNADJUSTED`, `SPLIT_ADJUSTED`, `BACK_ADJUSTED`, and `TOTAL_RETURN`.
- [x] T002 Update `database_schema.sql` to define the complete `corporate_actions` table with `action_id VARCHAR PRIMARY KEY`, `share_multiplier DOUBLE NOT NULL DEFAULT 1.0`, `bonus_new_shares`, `bonus_existing_shares`, `old_face_value`, `new_face_value`, and `recorded_at`.
- [x] T003 Update `storage/duckdb_manager.py` with `upsert_corporate_actions()`, `get_corporate_actions(symbol, start_date, end_date)`, and `get_all_corporate_actions()`.
- [x] T004 Update `data/corporate_actions_nifty200.json` with canonical `action_id`, `share_multiplier`, face value transitions, and exact bonus ratios.
- [x] T005 Update `tools/import_corporate_actions.py` to parse and import the seed fixture into DuckDB.

---

## Phase 2: User Story 1 - Split, Bonus, and Consolidation Multiplier Engine (Priority: P1)

**Goal**: Implement backward price division ($P / S_t$) and volume multiplication ($V \times S_t$) using canonical `share_multiplier` with strict IST session alignment and turnover invariance.

- [x] T006 [US1] Implement `PriceAdjustmentEngine.calculate_split_factors()` in `data_platform/adjustments.py` using `Asia/Kolkata` date conversion.
- [x] T007 [US1] Implement `PriceAdjustmentEngine.adjust_ohlcv()` for `PriceAdjustment.SPLIT_ADJUSTED` with turnover preservation ($P \times V = \text{invariant}$).
- [x] T008 [US1] Implement idempotency check in `PriceAdjustmentEngine.adjust_ohlcv()` to reject double-adjustments.
- [x] T009 [US1] Add unit tests in `tests/test_adjustments.py` for 10:1 split (Tata Steel boundary), 1:3 bonus ratio, 5:1 consolidation, and turnover invariance.

---

## Phase 3: User Story 2 - Backward Dividend Gap Adjustment (Priority: P2)

**Goal**: Implement continuous back-adjusted price levels (`BACK_ADJUSTED`) using previous active trading session close ($P_{\text{prev}}$).

- [x] T010 [US2] Implement `PriceAdjustmentEngine.calculate_dividend_factors()` in `data_platform/adjustments.py` finding the nearest previous trading session close.
- [x] T011 [US2] Implement `PriceAdjustmentEngine.adjust_ohlcv()` for `PriceAdjustment.BACK_ADJUSTED` ensuring dividends scale prices without scaling volume.
- [x] T012 [US2] Add unit tests in `tests/test_adjustments.py` verifying Friday-to-Monday dividend boundary and non-scaling of volume.

---

## Phase 4: User Story 3 - Exact Total Return Index & Series (Priority: P2)

**Goal**: Build `TotalReturnEngine` computing exact dividend-reinvested daily shareholder return ($r_t^{\text{TR}} = \frac{P_t + D_t}{P_{t-1}} - 1$) and cumulative index series ($\text{TRI}_t$).

- [x] T013 [US3] Implement `TotalReturnEngine.calculate_total_return_series()` and `TotalReturnEngine.build_total_return_index()` in `data_platform/adjustments.py`.
- [x] T014 [US3] Add unit tests in `tests/test_adjustments.py` for Total Return compounding calculation and comparison against back-adjusted prices.

---

## Phase 5: User Story 4 & 5 - Pipeline & Dataset Integration (Priority: P1)

**Goal**: Connect `StrategyPipeline` and `ResearchDataset` with strongly-typed `PriceAdjustment` and verify end-to-end backtesting.

- [x] T015 [US4] Update `trading_stack/pipeline.py` and `trading_stack/datasets.py` to enforce `PriceAdjustment` enum typing.
- [x] T016 [US4] Run end-to-end TATASTEEL split validation comparing unadjusted vs split-adjusted EMA/RSI continuity.
- [x] T017 Run full regression test suite across the entire project (`pytest -q`).
