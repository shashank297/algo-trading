# Feature Specification: Final Audit Remediation & Institutional Hardening

**Feature Directory**: `specs/008-final-audit-remediation`
**Created**: 2026-08-26
**Status**: Draft
**Input**: Comprehensive final audit remediation covering P0-3, P1-9, E-8, E-10, E-12, vectorized transaction costs, and promotion OOS evaluation.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - P0-3: Authoritative Receipt-Time Forward Paper Execution (Priority: P1)

As a quant trader running forward paper sessions, I need orders in `TRUE_NEXT_OPEN` mode to execute strictly upon receipt of an independently observed, trusted live opening tick with full token/exchange/symbol validation, and never fall back to legacy quotes or completed candle open prices.

**Why this priority**: Eliminates lookahead bias and timing causality violations during morning market opening rebalances.

**Independent Test**: Execute `ForwardPaperSessionEngine` and `ForwardPortfolioPaperSessionEngine` in `TRUE_NEXT_OPEN` mode with:
- Valid `OpeningTickObservation` -> fills at `received_at_utc` with observed tick price.
- Missing/degraded tick -> rejects order without executing against historical bar open.
- Wrong token/exchange -> rejects order.

**Acceptance Scenarios**:
1. **Given** a pending order from Day $T$, **When** Day $T+1$ morning tick arrives with valid `OpeningTickObservation` (`received_at_utc >= exchange_timestamp`), **Then** order fills at observed tick price with fill timestamp = `received_at_utc` and provenance recorded in fill metadata.
2. **Given** a pending order, **When** no trusted `OpeningTickObservation` is provided, **Then** order is rejected with `MISSED_LIVE_OPEN_PRICE` and zero fill.
3. **Given** a pending order, **When** observation token does not match instrument token, **Then** order is rejected.

---

### User Story 2 - P1-9 & E-10: Exact Immutable Lineage, DQ Binding & Run Certification (Priority: P1)

As a risk officer and strategy researcher, I need every strategy run (single-asset and portfolio) and its research frame to be bound to exact contributing dataset IDs, immutable content hashes, and exact 6-check DQ certifications, so that no run can ever be certified using stale, newer, or unrelated datasets.

**Why this priority**: Guarantees forensic auditability and eliminates data contamination across backtest, walk-forward, and promotion stages.

**Independent Test**: Run `StrategyPipeline` or `PortfolioEventBacktester`, construct `ResearchDataset`, verify exact dataset IDs and DQ certification IDs are stored in `research_frame_certifications`, and verify `RunCertificationService` validates exact run-bound hashes without falling back to latest database records.

**Acceptance Scenarios**:
1. **Given** a research dataset composed of multiple candle slices, **When** research frame is built, **Then** all contributing dataset IDs, content hashes, and exact DQ certification IDs are persisted in `research_frame_certifications`.
2. **Given** a completed run, **When** `RunCertificationService.certify(run_id)` runs, **Then** `DATA_LINEAGE` and `DATA_QUALITY` verify exact match with the run's stored `frame_certification_id` and fail closed on any discrepancy or missing check.
3. **Given** a promotion review, **When** `PromotionEngine.review(run_id)` is invoked, **Then** it verifies the certification bundle belongs to the exact run ID and data hash, and computes primary Sharpe/drawdown from stitched out-of-sample equity returns.

---

### User Story 3 - E-8: Stream Gap Recovery & Aggregator State Machine (Priority: P1)

As a live trading system operator, I need WebSocket packet sequence gaps to trigger degraded isolation, durable unrepaired gap logging with actual gap sizes, and a clean socket reconnection that re-anchors the future stream while isolating historical gaps until verified repair.

**Why this priority**: Prevents dropped ticks from silently corrupting live realtime bar aggregations or polluting live execution signals.

**Independent Test**: Simulate a sequence drop in `SmartAPIWebSocketClient`:
- Verifies `DEGRADED` state and exact `gap_size` logged.
- Disconnects and reconnects on a fresh generation.
- Closes open-ended untrusted interval at re-anchor in `RealtimeBarAggregator` while retaining historical gap.

**Acceptance Scenarios**:
1. **Given** an active WebSocket connection, **When** a sequence skip occurs (e.g. sequence 10 -> 15), **Then** gap of size 4 is recorded as `UNREPAIRED`, token is marked `DEGRADED`, and ticks are quarantined.
2. **Given** a degraded stream, **When** reconnect occurs on a new generation with positive baseline sequence, **Then** future stream is re-anchored and aggregator closes future untrusted interval up to re-anchor time.
3. **Given** an unrepaired historical interval, **When** system restarts, **Then** unrepaired gap is reloaded into aggregator on startup.

---

### User Story 4 - Vectorized Cost Parity & Position Sizing Accuracy (Priority: P2)

As a quant researcher running vectorized and single-asset paper strategies, I need vectorized runs to accurately apply the Indian delivery cost schedule and paper sessions to size positions against current equity rather than static initial capital.

**Why this priority**: Eliminates PnL discrepancies between vectorized screening and event-driven backtesting, and ensures realistic compounding during paper trading.

**Acceptance Scenarios**:
1. **Given** a vectorized backtest request, **When** `StrategyPipeline.run(mode='vectorized')` executes, **Then** `VectorizedBacktester` applies the configured `IndianDeliveryCostSchedule`.
2. **Given** an active single-asset paper session with accumulated profits, **When** new target signal is processed, **Then** position size is calculated from `current_equity = cash + quantity * price`.

---

### User Story 5 - E-12: Critical Module Test Coverage >= 95% & CI Green Gate (Priority: P1)

As a platform engineer, I need CI to enforce >=95% code coverage across all 11 critical trading and data modules, pass all type/lint gates (Mypy, Pyright, Ruff), and verify frontend build before any release.

**Why this priority**: Ensures no regressions can enter production.

**Acceptance Scenarios**:
1. **Given** full test suite, **When** `pytest` runs, **Then** 100% tests pass.
2. **When** critical coverage report is generated for `risk/*.py`, `trading_stack/*.py`, `smartapi/websocket_client.py`, `storage/migrations/*.py`, **Then** coverage is >= 95.0%.
3. **When** `mypy`, `pyright`, and `ruff` run, **Then** zero errors are reported.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `OpeningTickObservation` MUST require `symbol`, `exchange`, `token`, `price`, `exchange_timestamp`, `received_at_utc`, and `quality_state`, where `received_at_utc >= exchange_timestamp` and sequence/epoch are non-negative.
- **FR-002**: `TRUE_NEXT_OPEN` paper execution MUST consume only `OpeningTickObservation`, execute at `received_at_utc`, match `symbol`, `exchange`, and `token`, and reject on missing or degraded observation.
- **FR-003**: `ResearchDataset` and `SynchronizedPanelBuilder` MUST derive contributing dataset IDs from candle rows and bind exact DQ certification IDs and content hashes.
- **FR-004**: Authoritative DQ verification MUST check that the dataset has status `VERIFIED`, lifecycle `CANONICAL_PROMOTED`, matching content hash, non-empty validator version, status `CERTIFIED`, and exactly 6 zero-issue checks (`schema`, `ohlc_integrity`, `duplicates`, `session_alignment`, `missing_sessions`, `timestamp_integrity`).
- **FR-005**: `RunCertificationService` MUST resolve `DATA_LINEAGE` and `DATA_QUALITY` from the run's exact `frame_certification_id` and fail closed with zero fallbacks to `LIMIT 1` or latest database records.
- **FR-006**: Certification bundle creation MUST execute atomically in a single database transaction.
- **FR-007**: `PromotionEngine` MUST validate exact run and frame binding, and compute primary performance metrics (Sharpe, Drawdown) from stitched out-of-sample equity returns.
- **FR-008**: `SmartAPIWebSocketClient` MUST calculate and persist actual `gap_size`, quarantine degraded ticks, force reconnect on a new generation upon sequence drops, and re-anchor future stream with non-negative baseline.
- **FR-009**: `RealtimeBarAggregator` MUST support closing open-ended degraded intervals at re-anchor while retaining historical gaps, and reload unrepaired gaps on startup.
- **FR-010**: `VectorizedBacktester` MUST apply the effective cost schedule when invoked via `StrategyPipeline`.
- **FR-011**: Single-asset paper sizing MUST use current portfolio equity and empirical/parametric risk estimation.

### Key Entities

- **OpeningTickObservation**: Strongly-typed morning market observation with independent exchange and receipt timestamps.
- **ResearchDataset**: Immutable research data container binding panel data to contributing dataset IDs, content hashes, DQ certifications, and PIT hashes.
- **RunCertificationBundle**: Parent certification record linking 5 child category certifications (`DATA_LINEAGE`, `DATA_QUALITY`, `CAUSALITY`, `PIT_SURVIVORSHIP`, `OOS_WALK_FORWARD`) atomically to a strategy run.
- **StreamGapRecord**: Durable record of an observed packet sequence discontinuity including token, epoch, gap size, and repair status.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of automated tests pass deterministically across single-asset, portfolio, paper, certification, and live stream domains.
- **SC-002**: Critical module code coverage achieves >= 95.0% across all 11 designated platform files.
- **SC-003**: Overall repository test coverage achieves >= 80.0%.
- **SC-004**: Static type checking (Mypy and Pyright) reports 0 errors in strict mode across the codebase.
- **SC-005**: Linter (Ruff) reports 0 warnings or errors.
- **SC-006**: Full mass-research pipeline executes end-to-end without data quality or binder exceptions.
