# Production Readiness & Architecture Invariants

Audit date: 2026-08-20

Current decision: **READY for NIFTY 200 daily historical research; READY for forward paper trading with EOD_BATCH and TRUE_NEXT_OPEN execution modes; NOT READY for unverified minute live trading.**

The deterministic research and paper execution stack is operational with comprehensive anti-lookahead and fail-closed data quality invariants. Live order routing remains unavailable by design.

---

## 1. Verified Architecture Invariants

### Core Data Platform & Lineage (P0-1, P0-4, P1-9, E-10, E-14)
- **Canonical Split-Adjusted Basis**: Split-adjusted price basis is the default throughout all backtesting, research, and paper trading. Every dataset tracks immutable `source_basis`, `canonical_basis`, and `research_basis` lineage.
- **Point-in-Time Universe Isolation**: `SynchronizedPanelBuilder` verifies date-range PIT coverage and applies point-in-time constituent masking before cross-sectional score ranking, preventing survivorship bias.
- **Authoritative Data Quality Gate**: `load_candles()` strictly verifies `market_datasets` status (`VERIFIED` & `CANONICAL_PROMOTED`) and positive check certification across all required categories (`schema`, `ohlc_integrity`, `duplicates`, `session_alignment`, `missing_sessions`, `timestamp_integrity`).
- **Forensic Relational Integrity**: `DatabaseIntegrityValidator` enforces foreign keys across fills, orders, costs, snapshot members, and dataset lineage fail-closed.

### Execution Realism & Risk Management (P0-2, P0-3, P1-8, P1-11, P2-22)
- **Causal Lagged ADV**: ADV calculations strictly lag Day $T+1$ execution by 1 bar per symbol (`shift(1).rolling(20)`), preventing future volume lookahead.
- **Causal Paper Execution Modes**:
  - `EOD_BATCH`: Signals execute strictly at Day $T+1$ completed candle `close`. Mutating Day $T+1$ `open` has zero impact on execution price or size.
  - `TRUE_NEXT_OPEN`: Signals execute against observed opening ticks; missing opening ticks reject with `MISSED_LIVE_OPEN_PRICE` without fallback to completed bar open.
- **Mandatory Risk State Contract**: `RequiredRiskStateValidator` requires all core risk dimensions (`capital`, `current_gross_exposure`, `daily_pnl`, `current_drawdown`, `current_sector_exposure`, `open_position_count`, `daily_turnover_crore`, `estimated_portfolio_var_pct`), eliminating synthetic risk manufacture.
- **Live Calendar Metric Annualization**: Metric calculations dynamically derive trading days and session minutes from the active `MarketCalendar`.
- **Date-Effective Delivery Cost Schedules**: Transaction costs dynamically resolve historical statutory and broker rate schedules back to 2010 based on fill timestamp.

### Realtime Streaming & Orchestration (P1-14, P1-16, P2-25, E-1, E-8)
- **Multi-Window Watermark Live Aggregator**: Buffers active tick windows and advances event-time watermarks (`max_event_time - allowed_lateness`), handling out-of-order ticks within tolerance.
- **Non-Overlapping Worker Retries**: Task execution timeout tracks live threads and aborts retries if the previous worker remains alive, guaranteeing `max_concurrent == 1`.
- **Durable Raw Packet Persistence**: WebSocket binary packets pipe directly to `market_raw_packets` with atomic batch writes and dead-letter spooling.
- **Schema Evolution Runner**: `MigrationRunner` executes checksum-validated migration scripts fail-closed against tampering.

---

## 2. Verification Summary

- **Verified Commit A SHA**: `4af6964d977d128661dd7ce5697fac95c5c2fc67`
- **Audit Completion**: All 25 architectural findings (P0-1 to P2-25) and 15 operational invariants (E-1 to E-15) verified and signed off.
- **Deterministic Test Suite**: 269 passed tests across the repository.
- **Global Test Coverage**: 80% repository-wide line coverage meeting CI gating criteria.

```powershell
.\venv\Scripts\python.exe -m pytest -q
269 passed in test suite

.\venv\Scripts\coverage.exe report
TOTAL: 80% line coverage

.\venv\Scripts\python.exe -m compileall -q main.py research.py trading_stack tests storage smartapi data_platform risk validators tools operations orchestration experiments ai_research
Exit code 0
```
