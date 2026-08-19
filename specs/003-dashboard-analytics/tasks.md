# Feature Tasks: Dashboard Analytics Deep Dive

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Update `tools/dashboard/api/main.py` with the new endpoint routes (stubs)
- [x] T002 Update `tools/dashboard/ui/src/App.tsx` to add the new "Analytics" tab toggle state

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 Create `AnalyticsTab` container component in `tools/dashboard/ui/src/components/AnalyticsTab.tsx`

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Time-Series Performance Breakdown (Priority: P1)

**Goal**: Display strategy performance broken down by month and year.

**Independent Test**: Selecting a strategy shows a matrix/table correctly grouping historical returns into monthly/yearly buckets.

### Implementation for User Story 1

- [x] T004 [P] [US1] Implement `/api/runs/{run_id}/analytics/monthly` endpoint in `tools/dashboard/api/main.py`
- [x] T005 [P] [US1] Create `MonthlyReturnsMatrix.tsx` component in `tools/dashboard/ui/src/components/`
- [x] T006 [US1] Integrate `MonthlyReturnsMatrix` into `AnalyticsTab.tsx` and fetch data

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 - Trade Win/Loss Analysis (Priority: P1)

**Goal**: Detailed breakdown of winning versus losing trades and base-investment scaled profit.

**Independent Test**: Verifying that total trades equal the sum of profitable and negative trades, and the profit metrics align with raw ledger data scaled to 100k.

### Implementation for User Story 2

- [x] T007 [P] [US2] Implement `/api/runs/{run_id}/analytics/stats` endpoint in `tools/dashboard/api/main.py`
- [x] T008 [P] [US2] Create `TradeStatsCards.tsx` component in `tools/dashboard/ui/src/components/`
- [x] T009 [US2] Integrate `TradeStatsCards` into `AnalyticsTab.tsx` and fetch data

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 - Trade-Level Root Cause Analysis (RCA) (Priority: P2)

**Goal**: Exact ledger of individual trades with context for debugging edge cases.

**Independent Test**: Clicking into a specific stock's ledger shows chronological list of fills with timestamps and reasons.

### Implementation for User Story 3

- [x] T010 [P] [US3] Implement `/api/runs/{run_id}/analytics/ledger` endpoint in `tools/dashboard/api/main.py`
- [x] T011 [P] [US3] Create `RCALedgerGrid.tsx` component in `tools/dashboard/ui/src/components/`
- [x] T012 [US3] Integrate `RCALedgerGrid` into `AnalyticsTab.tsx` and fetch data

**Checkpoint**: All user stories should now be independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [x] T013 Run quickstart.md validation locally to verify the entire Analytics tab renders successfully
- [x] T014 Verify UI alignment and styling matches the premium dark-mode theme

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - User stories can then proceed sequentially in priority order (P1 → P2 → P3)
- **Polish (Final Phase)**: Depends on all desired user stories being complete
