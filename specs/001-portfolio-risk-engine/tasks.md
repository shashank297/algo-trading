# Feature Tasks: Portfolio Risk Engine

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Create `risk/` directory package with `__init__.py`
- [x] T002 Create `config/risk_limits.yaml` with default limits configuration

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 Create `TradeIntent` and `RiskEvaluation` models in `risk/models.py`
- [x] T004 Implement `risk_audit_log` schema setup and logging in `storage/duckdb_manager.py`

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Pre-trade validation of a compliant trade (Priority: P1) ⭐ MVP

**Goal**: Seamless interception of trades without breaking existing paths.

**Independent Test**: Route a dummy intent through the system and ensure execution.

### Implementation for User Story 1

- [x] T005 [US1] Create core `RiskEngine` class in `risk/engine.py` to process intents
- [x] T006 [US1] Modify `trading_stack/paper.py` to route intents through `RiskEngine`
- [x] T007 [US1] Modify `trading_stack/event_driven.py` (or `pipeline.py`) to route intents through `RiskEngine`
- [x] T008 [US1] Add test for baseline engine interception in `tests/test_risk.py`

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 - Position and Portfolio Exposure Limits (Priority: P1)

**Goal**: Block trades exceeding position size or portfolio concentration limits.

**Independent Test**: Reject trade intents that exceed limits.

### Implementation for User Story 2

- [x] T009 [P] [US2] Implement `PositionSizeValidator` in `risk/validators.py`
- [x] T010 [P] [US2] Implement `PortfolioExposureValidator` in `risk/validators.py`
- [x] T011 [US2] Integrate limits with `RiskEngine.validate()` inside `risk/engine.py`
- [x] T012 [US2] Add tests for position and portfolio limits in `tests/test_risk.py`

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 - Drawdown and Daily Loss Protection (Priority: P1)

**Goal**: Block new risk when portfolio enters severe drawdown or hits daily limits.

**Independent Test**: Reject trades when peak equity state implies drawdown limit breach.

### Implementation for User Story 3

- [x] T013 [P] [US3] Implement `DrawdownValidator` in `risk/validators.py`
- [x] T014 [P] [US3] Implement `DailyLossValidator` in `risk/validators.py`
- [x] T015 [US3] Integrate drawdown limits with `RiskEngine` in `risk/engine.py`
- [x] T016 [US3] Add tests for drawdown limits in `tests/test_risk.py`

**Checkpoint**: All user stories should now be independently functional

---

## Phase 6: User Story 4 - Sector Exposure Enforcement (Priority: P2)

**Goal**: Prevent sector-based concentration risk.

**Independent Test**: Overweight a specific sector in intents and verify rejection.

### Implementation for User Story 4

- [x] T017 [US4] Implement `SectorExposureValidator` in `risk/validators.py`
- [x] T018 [US4] Add tests for sector exposure limits in `tests/test_risk.py`

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [x] T019 Run quickstart.md validation locally
- [x] T020 Run full end-to-end `pytest` suite

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - User stories can then proceed sequentially in priority order (P1 → P2 → P3)
- **Polish (Final Phase)**: Depends on all desired user stories being complete
