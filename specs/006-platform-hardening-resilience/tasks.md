# Tasks: Platform Hardening & Ingestion Resilience

## Phase 1: Setup

- [x] T001 Verify project test baseline with pytest in `tests/`

---

## Phase 2: Foundational

- [x] T002 Update `HistoricalDataClient` constructor to accept an optional shared `RateLimiter` in `smartapi/historical.py`

---

## Phase 3: User Story 1 - Global Account-Wide Rate Limiting (Priority: P1)

**Goal**: Sequence all concurrent worker thread API requests through a single shared rate limiter.
**Independent Test**: Run 3-worker backfill and verify rate limits are strictly enforced across threads.

- [x] T003 [US1] Instantiate a single shared `RateLimiter` and pass it to worker clients in `tools/backfill_market_history.py`

---

## Phase 4: User Story 2 - Portfolio & Single-Asset Strategy Aggregation (Priority: P1)

**Goal**: Safely aggregate strategy metrics for both single-asset and cross-sectional portfolio runs.
**Independent Test**: Query `/api/strategies` and verify `total_stocks` is non-zero and accurately formatted.

- [x] T004 [US2] Update `get_strategies` query to handle non-colon run IDs in `tools/dashboard/api/main.py`

---

## Phase 5: User Story 3 - Dynamic Dashboard API Base URL (Priority: P2)

**Goal**: Support dynamic API base resolution for alternate ports, LAN addresses, and reverse proxies.
**Independent Test**: Load UI with custom origin and verify network requests route to the appropriate host.

- [x] T005 [US3] Add dynamic `API_BASE` resolution in `tools/dashboard/ui/src/components/AnalyticsTab.tsx`

---

## Phase 6: User Story 4 - Smart Local Caching for Instrument Master (Priority: P3)

**Goal**: Skip redundant 150MB instrument downloads on warm same-day startups.
**Independent Test**: Execute `download_instrument_master()` twice and verify second call loads cached JSON in <1s.

- [x] T006 [US4] Add same-day cache validation and local loading in `smartapi/instrument.py`

---

## Phase 7: Polish & Validation

- [x] T007 Run full pytest test suite across `tests/` to confirm all unit and integration tests pass
