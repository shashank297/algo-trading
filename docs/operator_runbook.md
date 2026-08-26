# Operator Runbook

Live order routing is unavailable by design. All execution commands below are research simulations or forward-only paper trading runs.

## 1. Preflight & Quality Verification

DuckDB enforces a single-writer constraint. Confirm no active background ingestion, backfill, or paper session is writing to `market_data.duckdb` before initiating another write process.

Run the standard quality gate suite:

```powershell
# 1. Deterministic Test Suite
.\venv\Scripts\python.exe -m pytest -q

# 2. Code Linting
.\venv\Scripts\python.exe -m ruff check .

# 3. Static Type Checking
.\venv\Scripts\python.exe -m mypy ai_research data_platform experiments operations orchestration risk smartapi storage trading_stack validators tools main.py research.py scheduler.py

# 4. Dependency Vulnerability Audit
.\venv\Scripts\python.exe -m pip_audit -r requirements.txt
```

---

## 2. Data Operations

### Universe Ingestion & Backfill
```powershell
# Ingest NIFTY 200 universe daily history
.\venv\Scripts\python.exe main.py --universe-snapshot NIFTY200_2026_08_17 --benchmark NIFTY200

# Resumable multi-timeframe historical backfill (1d, 1m)
.\venv\Scripts\python.exe tools\backfill_market_history.py --universe-snapshot NIFTY200_2026_08_17 --start-date 2012-01-01 --timeframes 1m,1d --max-workers 3

# Offline data quality revalidation
.\venv\Scripts\python.exe tools\refresh_session_quality.py --timeframe 1d --universe-snapshot NIFTY200_2026_08_17 --benchmark NIFTY200

# Verify Point-in-Time universe readiness
.\venv\Scripts\python.exe research.py --command universe-status --universe-snapshot NIFTY200_2026_08_17 --timeframe 1d --benchmark NIFTY200
```

> **Important**: Backfill is resumable. An empty pre-listing window is a provider boundary, not permission to manufacture prices.

---

## 3. Research & Forward Paper Trading

### Research & Backtesting
```powershell
# Run cross-sectional portfolio experiment
.\venv\Scripts\python.exe research.py --command portfolio-experiment --strategy cross_sectional_momentum --universe-snapshot NIFTY200_2026_08_17 --timeframe 1d --mode event-driven --benchmark NIFTY200

# Promote approved run to paper trading candidate
.\venv\Scripts\python.exe research.py --command promote --run-id <RUN_ID> --paper-approved
```

### Forward Paper Trading
```powershell
# Advance cross-sectional paper session (EOD_BATCH mode)
.\venv\Scripts\python.exe research.py --command paper --strategy cross_sectional_momentum --run-id <RUN_ID> --universe-snapshot NIFTY200_2026_08_17 --timeframe 1d --benchmark NIFTY200 --execution-mode EOD_BATCH

# Single-asset paper session (TRUE_NEXT_OPEN mode)
.\venv\Scripts\python.exe research.py --command paper --strategy trend_following --run-id <RUN_ID> --symbol RELIANCE-EQ --timeframe 1d --execution-mode TRUE_NEXT_OPEN
```

> **Invariant**: Paper sessions process only newly observed bars. Watermarks advance strictly monotonically and must never be deleted to force retroactive replay.

---

## 4. Web Dashboard Service

```powershell
# 1. Start backend API in read-only mode
.\venv\Scripts\python.exe -m uvicorn tools.dashboard.api.main:app --port 8000 --reload

# 2. Build and start frontend UI
cd tools\dashboard\ui
npm run dev
```

---

## 5. Database Backup & Disaster Recovery

Stop all writer processes before creating or restoring database backups.

```powershell
# Create database backup
.\venv\Scripts\python.exe tools\database_recovery.py backup --database market_data.duckdb --output backups\market_data-YYYYMMDD.duckdb

# Verify backup integrity and checksums
.\venv\Scripts\python.exe tools\database_recovery.py verify --backup backups\market_data-YYYYMMDD.duckdb

# Restore database from backup
.\venv\Scripts\python.exe tools\database_recovery.py restore --backup backups\market_data-YYYYMMDD.duckdb --database restored.duckdb
```

---

## 6. Incident Response

- `CRITICAL`: Duplicate, future, null, or invalid OHLCV data. Stop research and paper processes immediately, preserve diagnostic logs, and restore from verified backup.
- `ERROR`: Missing candles or session alignment gaps. Disable affected symbols and investigate provider stream or corporate action logs.
- `WARNING`: Statistical anomalies or high slippage observations. Review trade attribution and fill cost breakdowns.
- Stale research tasks in the orchestrator transition to `RETRYING` or `FAILED`; superseded tasks are marked `CANCELLED` and never silently resumed.
