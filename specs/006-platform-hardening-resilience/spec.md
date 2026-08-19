# Feature Specification: Platform Hardening & Ingestion Resilience

**Feature Branch**: `006-platform-hardening-resilience`

**Created**: 2026-08-20

**Status**: Draft

**Input**: User description: "Apply all identified improvements and fixes step by step: shared rate limiting across multi-threaded ingestion workers, robust portfolio strategy symbol aggregation in dashboard API, dynamic frontend API URL resolution, and same-day instrument caching."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Global Account-Wide Rate Limiting in Multi-Threaded Backfill (Priority: P1)

As a quantitative researcher running multi-worker market history downloads, I want all worker threads to share a synchronized, global rate limiter, so that concurrent requests never exceed the broker's 3 requests/sec rate limit.

**Why this priority**: Exceeding rate limits causes immediate API throttling, dropped connection sockets, and temporary account bans from Angel One.

**Independent Test**: Run a 3-worker backfill job and observe that total outbound request timestamps across all threads maintain at least a 334ms separation between calls.

**Acceptance Scenarios**:
1. **Given** 3 concurrent backfill workers downloading different stock histories, **When** all workers request data simultaneously, **Then** all calls are sequenced through a shared limiter and 0 rate-limit violations occur.

---

### User Story 2 - Portfolio & Single-Asset Strategy Aggregation in Dashboard (Priority: P1)

As a trader reviewing backtested strategies on the dashboard, I want the strategy overview table to accurately display symbol counts and performance metrics for both single-asset and cross-sectional portfolio strategies.

**Why this priority**: Currently, portfolio strategies without colon-separated run IDs can produce empty or malformed symbol attributes in the strategy aggregate query.

**Independent Test**: Load the dashboard overview endpoint `/api/strategies` when both single-asset (e.g. `bollinger_pullback`) and cross-sectional (e.g. `cross_sectional_momentum`) strategies are present, and verify that `total_stocks` is accurate for all rows.

**Acceptance Scenarios**:
1. **Given** a cross-sectional portfolio run with 200 stocks, **When** `/api/strategies` is queried, **Then** `total_stocks` is properly reported and `strategy_name` aggregates all historical runs without null or empty strings.

---

### User Story 3 - Dynamic Dashboard API Base URL (Priority: P2)

As a trader accessing the web dashboard from a different browser or network machine, I want the web interface to dynamically determine the backend API host, so that analytics and charts load seamlessly regardless of host port or IP.

**Why this priority**: Hardcoded `http://localhost:8000/api` prevents viewing the dashboard from other local devices on the LAN or containerized environments.

**Independent Test**: Access the UI on a remote host or via a proxied port and verify that all chart and ledger API requests successfully connect to the running API server.

**Acceptance Scenarios**:
1. **Given** the dashboard UI running on a custom port or IP, **When** a user navigates to the Deep Dive Analytics tab, **Then** the browser sends API calls to the matching host/port.

---

### User Story 4 - Smart Local Caching for Instrument Master (Priority: P3)

As a developer starting research scripts or the pipeline, I want the system to avoid re-downloading the ~150MB instrument master file if an up-to-date copy from today is already cached on disk.

**Why this priority**: Eliminates 5–10 seconds of startup delay on every pipeline and backfill execution.

**Independent Test**: Run the backfill script twice on the same day and verify that the second run completes startup in under 1 second without an HTTP request to the instrument URL.

**Acceptance Scenarios**:
1. **Given** a valid `data/instrument_master.json` downloaded today, **When** a script initializes `InstrumentMaster`, **Then** it loads the local cache directly.

---

### Edge Cases

- What happens if the local instrument master file is corrupted or 0 bytes? (The system must detect the invalid JSON and automatically re-download).
- What happens if a broker token expires while multiple workers are waiting on the shared rate limiter? (The token refresh must lock, refresh once, and all workers resume with the new token).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `HistoricalDataClient` and `RateLimiter` MUST support sharing a single limiter instance across any number of worker threads.
- **FR-002**: The Dashboard API (`/api/strategies`) MUST handle `run_id` strings without colons by falling back to `sr.symbol` or a default `'PORTFOLIO'` identifier.
- **FR-003**: The Dashboard UI components MUST use a configurable or dynamic API base URL fallback.
- **FR-004**: `InstrumentMaster` MUST check the date of existing local cache files before initiating a network download.

### Key Entities

- **RateLimiter**: Shared concurrency governor enforcing per-second and per-minute quotas.
- **StrategyAggregate**: API response model representing portfolio- and single-asset-level summary metrics.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of concurrent backfill requests comply with the account-wide 3 req/sec rate limit.
- **SC-002**: Zero `split_part` string truncation errors when displaying cross-sectional portfolio strategies on the dashboard.
- **SC-003**: Startup time for ingestion tools decreases by >80% on warm cache runs.

## Assumptions

- Angel One SmartAPI maintains a fixed 3 requests per second limit per client account.
- The instrument master list updates only once per day before market open.
