# Operator Runbook

Live order routing is unavailable. All execution commands below are research or paper-only.

## Preflight

Run one DuckDB writer at a time. Confirm no ingestion, backfill, archive, research, or paper process is active before starting another writer.

```powershell
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\ruff.exe check .
.\venv\Scripts\mypy.exe ai_research data_platform experiments operations orchestration risk smartapi storage trading_stack validators
.\venv\Scripts\pip-audit.exe -r requirements.txt --cache-dir .pip-audit-cache
```

## Data Operations

Refresh the immutable NIFTY 200 universe and daily/minute history:

```powershell
.\venv\Scripts\python.exe main.py --universe-snapshot NIFTY200_2026_08_17
.\venv\Scripts\python.exe tools\backfill_market_history.py --universe-snapshot NIFTY200_2026_08_17 --start-date 2012-01-01 --timeframes 1m,1d --max-workers 3
.\venv\Scripts\python.exe tools\refresh_session_quality.py --timeframe 1d --universe-snapshot NIFTY200_2026_08_17 --benchmark NIFTY200
.\venv\Scripts\python.exe research.py --command universe-status --universe-snapshot NIFTY200_2026_08_17 --timeframe 1d --benchmark NIFTY200
```

Backfill is resumable. An empty pre-listing window is a provider boundary, not permission to manufacture prices.
Run `refresh_session_quality.py` after changing calendar evidence or overrides. Do not make the calendar broader merely to clear unexplained timestamps; classify or quarantine them first.

## Research And Paper

Run authoritative portfolio research before RCA or promotion:

```powershell
.\venv\Scripts\python.exe research.py --command portfolio-experiment --strategy cross_sectional_momentum --universe-snapshot NIFTY200_2026_08_17 --timeframe 1d --mode event-driven --benchmark NIFTY200
.\venv\Scripts\python.exe research.py --command promote --run-id RUN_ID --paper-approved
.\venv\Scripts\python.exe research.py --command paper --strategy cross_sectional_momentum --run-id RUN_ID --universe-snapshot NIFTY200_2026_08_17 --timeframe 1d --benchmark NIFTY200
```

Promotion must pass deterministic checks and record human approval before paper activation. Paper sessions process only newly observed bars. Never delete their watermark to force historical replay.

## Backup And Restore

Stop all writers before backup or restore.

```powershell
.\venv\Scripts\python.exe tools\database_recovery.py backup --database market_data.duckdb --output backups\market_data-YYYYMMDD.duckdb
.\venv\Scripts\python.exe tools\database_recovery.py verify --backup backups\market_data-YYYYMMDD.duckdb
.\venv\Scripts\python.exe tools\database_recovery.py restore --backup backups\market_data-YYYYMMDD.duckdb --database restored.duckdb
```

Restore refuses to overwrite an existing database unless `--overwrite` is explicitly supplied. Validate readiness against the restored copy before replacing production data.

## Incident Response

- `CRITICAL`: duplicate, future, null, or invalid OHLCV data. Stop research and paper processes, preserve logs, and restore or re-import verified observations.
- `ERROR`: missing candles or session alignment gaps. Disable affected symbols and investigate calendar/provider evidence.
- `WARNING`: statistical anomalies. Review, but do not page or delete observations automatically.
- Stale research jobs are moved to `RETRYING` or `FAILED`; superseded jobs are `CANCELLED` and never silently resumed.
