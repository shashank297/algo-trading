# Production Readiness & Architecture Invariants

Audit date: 2026-08-28
Audit Scope: **Phase 2.3 causal evidence remediation & invariant enforcement**
Verified Implementation Commit: `5e33bcc0516c1e6d340cd7f13776c1f2819a550e`

Current decision: **Phase 2.3 causal-evidence remediation is locally verified on the SHA above. Post-remediation CI confirmation is still pending, so current main is not fully verified. Live/real-money readiness remains NOT READY.**

The deterministic research and paper execution stack is operational with comprehensive anti-lookahead, fail-closed data quality invariants, exact frame lineage, generation-isolated stream recovery, and stitched out-of-sample promotion gates. Live order routing remains unavailable by design.

---

## 1. Verified Architecture Invariants & Audit Remediation Summary

### Core Data Platform & Lineage (P0-1, P0-4, P1-9, E-10, E-14, D-1)
- **Canonical Split-Adjusted Basis**: Split-adjusted price basis is the default throughout all backtesting, research, and paper trading. Every dataset tracks immutable `source_basis`, `canonical_basis`, and `research_basis` lineage.
- **Point-in-Time Universe Isolation**: `SynchronizedPanelBuilder` verifies date-range PIT coverage and applies point-in-time constituent masking before cross-sectional score ranking, preventing survivorship bias.
- **Authoritative Exact Data Quality & Lineage Gate (P1-9, D-1)**: Eliminated all latest-cert fallbacks (`ORDER BY completed_at DESC LIMIT 1`). Research frame creation requires exact dataset content hash match and zero-issue certification across 6 child checks (`schema`, `ohlc_integrity`, `duplicates`, `session_alignment`, `missing_sessions`, `timestamp_integrity`). Persists full `dataset_evidence_json`, `dq_certification_ids_json`, and `pit_evidence_hash` on frame records. Single-asset walk forward evaluations strictly preserve all 5 exact lineage fields across train/test splits.
- **Forensic Relational Integrity**: `DatabaseIntegrityValidator` enforces foreign keys across fills, orders, costs, snapshot members, and dataset lineage fail-closed.

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
- **Schema Evolution Runner**: `MigrationRunner` executes checksum-validated migration scripts (001 through 013) fail-closed against tampering.

### Certification & Stitched OOS Promotion (E-10, D-2)
- **Exact Run Certification**: `RunCertificationService` evaluates 5 categories (`DATA_LINEAGE`, `DATA_QUALITY`, `CAUSALITY`, `PIT_SURVIVORSHIP`, `OOS_WALK_FORWARD`), verifies exact frame certification and DQ certificates without latest-dataset fallback, and writes atomic certification bundles.
- **Pure Stitched Out-of-Sample Returns Evaluation (D-2)**: `PromotionEngine` calculates primary Sharpe ratio and Maximum Drawdown exclusively from concatenated out-of-sample equity returns (`evidence_level = 'OUT_OF_SAMPLE'`). Fails closed on missing or insufficient out-of-sample data with zero in-sample metric fallbacks.

---

## 2. Verification Summary

- **Current locally verified SHA**: `5e33bcc0516c1e6d340cd7f13776c1f2819a550e`
- **Deterministic Test Suite**: 506 passed tests across the repository (3 expected corporate-action basis warnings).
- **Compilation**: `compileall` completed cleanly for `main.py`, `research.py`, `trading_stack`, and `tests`.
- **CI status for the current SHA**: pending; do not treat the historical CI/coverage/static-analysis results below as evidence for this remediation SHA.

### Historical baseline evidence (prior commit only)

- **Prior verified SHA**: `10bdd650158b15a3cb6043b15249d8b2f2b0a4fa`
- **GitHub Actions Evidence**: CI run #28 succeeded on the verified SHA: Linux Python 3.12, Linux Python 3.13, Windows Python 3.12, quality, gitleaks, and frontend jobs all passed.
- **Deterministic Test Suite**: 405 passed tests across the repository (3 expected corporate-action basis warnings).
- **Global Test Coverage**: 84% repository-wide line coverage (exceeds 80% CI threshold).
- **Critical Path Module Coverage**: 95% critical line coverage across execution, risk, streaming, aggregation, and certification modules (exceeds 95% CI threshold).
- **Static Analysis & Type Checking**:
  - `mypy`: 0 issues.
  - `pyright`: 0 errors.
  - `ruff`: 0 lint errors across repository.
  - `compileall`: 100% clean compilation.
  - `pip-audit`: No known vulnerabilities found.
  - `frontend UI build`: `npm run build` succeeds cleanly with 0 TypeScript errors.

```powershell
.\venv\Scripts\python.exe -m pytest -q
# Output: 405 passed, 3 warnings

.\venv\Scripts\python.exe -m coverage report --fail-under=80
# Output: TOTAL 84% line coverage

.\venv\Scripts\python.exe -m coverage report --include="risk/*.py,trading_stack/paper.py,trading_stack/portfolio.py,trading_stack/portfolio_paper.py,trading_stack/pipeline.py,trading_stack/datasets.py,trading_stack/certification.py,trading_stack/promotion.py,smartapi/websocket_client.py,trading_stack/live_aggregator.py,storage/migrations/*.py" --fail-under=95
# Output: TOTAL 95% line coverage

.\venv\Scripts\python.exe -m ruff check .
# Output: All checks passed!

.\venv\Scripts\python.exe -m mypy ai_research data_platform experiments operations orchestration risk smartapi storage trading_stack validators tools main.py research.py scheduler.py
# Output: Success: no issues found in 85 source files

pyright
# Output: 0 errors

.\venv\Scripts\python.exe -m compileall -q main.py research.py scheduler.py ai_research data_platform experiments operations orchestration risk smartapi storage trading_stack validators tools tests
# Output: Exit code 0

.\venv\Scripts\python.exe -m pip_audit -r requirements.txt
# Output: No known vulnerabilities found

cd tools/dashboard/ui ; npm run build ; cd ../../..
# Output: vite build complete (0 errors)
```

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
