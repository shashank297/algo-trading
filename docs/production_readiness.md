# Production Readiness & Architecture Invariants

Audit date: 2026-08-28
Audit Scope: **Phase 2.3 final causal-evidence remediation and Phase 2.4 implementation evidence**
Verified Implementation Commit: `bb0726b8461ccc1c36efec8f120ce22f6e466355`
Verified Exact-Head PR CI: [run #74](https://github.com/shashank297/algo-trading/pull/2/checks) — all six configured jobs passed.

Current decision: **Phase 2.3 remediation is closed on the verified implementation SHA above. Phase 2.4 is implemented and awaits protected-branch merge. This certification-record commit must receive exact-head green CI before final remote certification. Live/real-money readiness remains NOT READY.**

The deterministic research and paper execution stack is operational with comprehensive anti-lookahead, fail-closed data quality invariants, exact frame lineage, generation-isolated stream recovery, point-in-time market regime classification, and stitched out-of-sample promotion gates. Live order routing remains unavailable by design.

---

## 1. Verified Architecture Invariants & Audit Remediation Summary

### Core Data Platform & Lineage (P0-1, P0-4, P1-9, E-10, E-14, D-1)
- **Canonical Split-Adjusted Basis**: Split-adjusted price basis is the default throughout all backtesting, research, and paper trading. Every dataset tracks immutable `source_basis`, `canonical_basis`, and `research_basis` lineage.
- **Point-in-Time Universe Isolation**: `SynchronizedPanelBuilder` and `PointInTimeUniverseManager` verify date-range PIT coverage and apply point-in-time constituent masking with knowledge-time causality (`known_at <= decision_time`), preventing survivorship bias.
- **Authoritative Exact Data Quality & Lineage Gate (P1-9, D-1)**: Eliminated all uncertified fallbacks. Research frame creation and regime bar loading require exact dataset content hash match and zero-issue certification across 6 child checks (`schema`, `ohlc_integrity`, `duplicates`, `session_alignment`, `missing_sessions`, `timestamp_integrity`) with `completed_at <= decision_time`. Persists full `dataset_evidence_json`, `dq_certification_ids_json`, and `pit_evidence_hash` on frame records.
- **Forensic Relational Integrity**: `DatabaseIntegrityValidator` enforces foreign keys across fills, orders, costs, snapshot members, and dataset lineage fail-closed.

### Market Context & Deterministic Regime Engine (Phase 2.3)
- **Strict Point-in-Time Causality**: All market evidence satisfies `known_at <= decision_time` and `bar_available_at <= decision_time`. No future or unconfirmed data is accessible during historical evaluation.
- **Context-Isolated Indicators**: In `INTRADAY` context, daily-style features are computed strictly on completed sessions ($D-1$); certified intraday bars remain evidence-only and are never merged into daily series.
- **Authoritative DQ Admission with Causal Fallback**: Dataset admission enforces `status = 'VERIFIED'`, `lifecycle_status = 'CANONICAL_PROMOTED'`, valid hash-bound `data_quality_certifications` completed before `decision_time`, and falls back newest-to-oldest within each timeframe until a candidate has causally usable bars. Intraday priority remains `1m → 5m → 15m → 30m → 60m`.
- **Cryptographic Evidence Manifest**: Full manifest mapping daily/intraday benchmark sources, VIX provenance, PIT universe member manifests, and model/policy/calendar versions is cryptographically bound into `input_evidence_hash` and deterministic UUIDv5 `regime_id`.
- **Zero Synthetic Metric Manufacture**: Missing optional evidence (e.g. VIX) deterministically reduces confidence; critical deficits produce `INSUFFICIENT_CONTEXT` without fabricating neutral defaults.

### Execution Realism & Risk Management (P0-2, P0-3, P1-8, P1-11, P2-22, D-3, D-4, D-5, D-6, D-7)
- **Causal Lagged ADV**: ADV calculations strictly lag Day $T+1$ execution by 1 bar per symbol (`shift(1).rolling(20)`), preventing future volume lookahead.
- **Strictly Typed Forward Paper Execution Modes (P0-3, D-3)**:
  - `EOD_BATCH`: Signals execute strictly at Day $T+1$ completed candle `close`. Mutating Day $T+1$ `open` has zero impact on execution price or size.
  - `TRUE_NEXT_OPEN`: Signals execute against strictly typed `OpeningTickObservation` (`received_at_utc >= exchange_timestamp`, non-negative sequence number and stream epoch). Enforces strict fail-closed token identity matching against resolved authoritative `instrument_master`, `universe_snapshot_members`, `index_constituents_pit`, or `historical_candles` records. Unresolved or mismatched tokens reject immediately with `MISSED_LIVE_OPEN_PRICE`.
- **Cost Model & Vectorized Parity**: `StrategyPipeline.run(mode='vectorized')` enforces execution cost schedules via `VectorizedBacktester(execution_model=execution_model)`.
- **Dynamic Paper Sizing & Parametric VaR (D-4)**: Single-asset and portfolio paper engines size targets against marked-to-market `current_equity = cash + quantity * price`; portfolio risk uses observed 20-session return volatility and projected gross exposure, never a fixed volatility proxy.
- **Independent Paper Ledger Reconciliation (D-5)**: Paper reconciliation compares durable `paper_position_intents` with immutable fill-derived positions, reporting real numerical position drift.
- **Mandatory Risk State Contract (D-6)**: `RequiredRiskStateValidator` requires all core risk dimensions (`capital`, `current_gross_exposure`, `daily_pnl`, `current_drawdown`, `current_sector_exposure`, `open_position_count`, `daily_turnover_crore`, `estimated_portfolio_var_pct`), eliminating synthetic risk manufacture across research and AI workflows.
- **Monotonic ATR Trailing Stop Ratchet (D-7)**: Strategy ATR stops track highest high since entry and ratchet strictly upward for long positions, never loosening stop levels.
- **Live Calendar Metric Annualization**: Metric calculations dynamically derive trading days and session minutes from the active `MarketCalendar`.
- **Date-Effective Delivery Cost Schedules**: Transaction costs dynamically resolve historical statutory and broker rate schedules back to 2010 based on fill timestamp.

### Realtime Streaming & Gap Recovery (P1-14, P1-16, P2-25, E-1, E-8)
- **Generation-Isolated WebSocket Client (E-8)**: Enforces WebSocket reconnection across fresh socket instances (`ws.close()`) rather than replaying subscriptions on degraded sockets. Canonical gap callbacks carry exact gap IDs and durable evidence.
- **Restart-Safe Gap Quarantine**: `SmartAPIWebSocketClient.restore_unresolved_gaps()` restores canonical unresolved state before startup. Canonical ledger-write failure creates an atomic durable recovery marker; startup, reconnect, open, and authoritative dispatch remain blocked until explicit recovery.
- **Exact Re-Anchor & Repair Semantics**: `RealtimeBarAggregator` closes only the named gap at re-anchor time and retains its historical interval as untrusted until explicit verified backfill repair.
- **Multi-Window Watermark Live Aggregator**: Buffers active tick windows and advances event-time watermarks (`max_event_time - allowed_lateness`), handling out-of-order ticks within tolerance.
- **Non-Overlapping Worker Retries**: Task execution timeout tracks live threads and aborts retries if the previous worker remains alive, guaranteeing `max_concurrent == 1`.
- **Durable Raw Packet Persistence**: WebSocket binary packets pipe directly to `market_raw_packets` with atomic batch writes and dead-letter spooling.
- **Schema Evolution Runner**: `MigrationRunner` executes checksum-validated migration scripts (001 through 020) fail-closed against tampering.

### Operational Regime Transition (Phase 2.4)
- **Two-Layer Regime State**: Immutable Phase 2.3 raw snapshots remain distinct from restart-safe operational regime and risk-state transitions.
- **Causal Hysteresis and Stress Evidence**: Policy-aware replay, confirmation dwell, confidence buffering, and separate `NORMAL`/`CAUTION`/`STRESS` state prevent regime thrashing without changing raw classifications.
- **Merge Status**: Implemented on the verified PR head above; protected-branch approval and merge remain required before `main` certification.

### Certification & Stitched OOS Promotion (E-10, D-2)
- **Exact Run Certification**: `RunCertificationService` evaluates 5 categories (`DATA_LINEAGE`, `DATA_QUALITY`, `CAUSALITY`, `PIT_SURVIVORSHIP`, `OOS_WALK_FORWARD`), verifies exact frame certification and DQ certificates without latest-dataset fallback, and writes atomic certification bundles.
- **Pure Stitched Out-of-Sample Returns Evaluation (D-2)**: `PromotionEngine` calculates primary Sharpe ratio and Maximum Drawdown exclusively from concatenated out-of-sample equity returns (`evidence_level = 'OUT_OF_SAMPLE'`). Fails closed on missing or insufficient out-of-sample data with zero in-sample metric fallbacks.

---

## 2. Verification Summary

- **Deterministic Test Suite**: 537 passed tests across the repository (3 expected corporate-action basis warnings).
- **Global Test Coverage**: 85% repository-wide line coverage (exceeds 80% CI threshold).
- **Critical Path Module Coverage**: 96% critical line coverage, including `trading_stack/regime_transition.py` (exceeds 95% CI threshold).
- **Static Analysis & Type Checking**:
  - `mypy`: 0 issues across 92 source files.
  - `pyright`: 0 errors / 538 warnings.
  - `ruff`: 0 lint errors across repository.
  - `compileall`: 100% clean compilation.
  - `pip-audit`: No known vulnerabilities found.
  - `frontend UI build`: `npm run build` succeeds cleanly with 0 TypeScript errors.

```powershell
.\venv\Scripts\python.exe -m pytest -q
# Output: 537 passed, 3 warnings

.\venv\Scripts\python.exe -m coverage report --fail-under=80
# Output: TOTAL 85% line coverage

.\venv\Scripts\python.exe -m coverage report --include="risk/*.py,trading_stack/paper.py,trading_stack/portfolio.py,trading_stack/portfolio_paper.py,trading_stack/pipeline.py,trading_stack/datasets.py,trading_stack/certification.py,trading_stack/promotion.py,trading_stack/regime_transition.py,smartapi/websocket_client.py,trading_stack/live_aggregator.py,storage/migrations/*.py" --fail-under=95
# Output: TOTAL 96% line coverage

.\venv\Scripts\python.exe -m ruff check .
# Output: All checks passed!

.\venv\Scripts\python.exe -m mypy ai_research data_platform experiments operations orchestration risk smartapi storage trading_stack validators tools main.py research.py scheduler.py
# Output: Success: no issues found in 92 source files

pyright
# Output: 0 errors / 538 warnings

.\venv\Scripts\python.exe -m compileall -q main.py research.py scheduler.py ai_research data_platform experiments operations orchestration risk smartapi storage trading_stack validators tools tests
# Output: Exit code 0

.\venv\Scripts\python.exe -m pip_audit -r requirements.txt
# Output: No known vulnerabilities found

cd tools/dashboard/ui ; npm run build ; cd ../../..
# Output: vite build complete (0 errors)
```

### Branch Governance

- `main` requires a pull request with one approving review, current-branch status, and all six configured checks: Ubuntu 3.12, Ubuntu 3.13, Windows 3.12, quality, frontend, and secrets.
- Force pushes, branch deletion, and administrator bypass are disabled.

---

## 3. Operational Invariants & Production Deployment Prerequisites

Before enabling live market data or executing paper trading in production environments, the following operational requirements must be satisfied:

1. **Authentication & Secret Management**:
   - `config/config.yaml` must not be checked into version control.
   - Angel One credentials (`api_key`, `client_code`, `pin`, `totp_secret`) must be supplied via secure environment variables or vault.
2. **Network & Clock Synchronization**:
   - Trading host system clock must be synchronized via NTP with < 100ms drift.
   - Network connectivity to Angel One WebSocket endpoints (`wss://smartapisocket.angelone.in/smart-stream`) must provide dedicated throughput without packet loss.
3. **Database Concurrency & Persistence**:
   - DuckDB operates under single-writer locking. Only one primary ingestion or orchestration process may write to `market_data.duckdb` at a time.
   - Research, backtest, and dashboard processes access the database in read-only mode or via transactional locks.
4. **Paper Trading Incubation**:
   - Strategies seeking promotion must undergo a minimum of 20 consecutive trading days of forward paper execution under `EOD_BATCH` or `TRUE_NEXT_OPEN` modes with zero reconciliation discrepancies before live capital consideration.
5. **Human Oversight & Kill Switches**:
   - Emergency kill switch (`risk.kill_switch_active = true`) must be accessible to operators at all times.
