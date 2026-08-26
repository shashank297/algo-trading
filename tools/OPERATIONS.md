# Algo Trading Platform Operations Runbook

## 1. System Architecture & Constraints

- **Storage Engine**: DuckDB (`market_data.duckdb`).
- **Concurrency Rule**: DuckDB enforces a strict **single-writer process** constraint. Never run two background processes that write to `market_data.duckdb` simultaneously. Read paths (such as research inspection, dashboards, and reports) must use `read_only=True`.
- **Trading Calendar**: Official NSE trading calendar (09:15 to 15:30 IST) with versioned session overrides and Point-in-Time constituent tracking.

---

## 2. Ingestion & Market Data Operations

### Historical Ingestion (NIFTY200 Universe)
```powershell
.\venv\Scripts\python.exe main.py --universe-snapshot NIFTY200_2026_08_17
```

### Gap Repair & Revalidation
```powershell
.\venv\Scripts\python.exe tools/revalidate_historical_datasets.py
```

### Corporate Actions & Benchmark Data Ingestion
```powershell
.\venv\Scripts\python.exe tools/import_corporate_actions.py
.\venv\Scripts\python.exe tools/import_benchmark.py
```

### Live WebSocket Streaming
```powershell
.\venv\Scripts\python.exe main.py --live-ticker --stream-mode SNAP_QUOTE --universe-snapshot NIFTY200_2026_08_17
```

---

## 3. Strategy Research & Backtesting

### Point-in-Time Universe Status
```powershell
.\venv\Scripts\python.exe research.py --command universe-status --universe-snapshot NIFTY200_2026_08_17
```

### Strategy Backtest (Single / Portfolio)
```powershell
.\venv\Scripts\python.exe research.py --command backtest --strategy trend_following --universe-snapshot NIFTY200_2026_08_17 --timeframe 1d
.\venv\Scripts\python.exe research.py --command backtest --strategy cross_sectional_momentum --universe-snapshot NIFTY200_2026_08_17 --timeframe 1d
```

### Walk-Forward Optimization
```powershell
.\venv\Scripts\python.exe research.py --command walk-forward --strategy cross_sectional_momentum --universe-snapshot NIFTY200_2026_08_17
```

### Strategy Promotion to Forward Paper Trading
```powershell
.\venv\Scripts\python.exe research.py --command promote --run-id <APPROVED_RUN_ID>
```

---

## 4. Forward Paper Trading

### Forward Paper Execution Modes
1. **TRUE_NEXT_OPEN**:
   - Signal generated on Day $T$ 15:30 close $\to$ pending order persisted.
   - On Day $T+1$ morning (~09:15), observe live opening quote/tick and execute order using Day $T$ valuations and 20-day lagged ADV.
2. **EOD_BATCH**:
   - Day $T$ 15:30 signal processed during batch run $\to$ executed at completed session close or scheduled for next trading session.

---

## 5. Web Dashboard & API

### Start Backend API (Read-Only Connection)
```powershell
.\venv\Scripts\python.exe -m uvicorn tools.dashboard.api.main:app --port 8000 --reload
```

### Start Frontend UI
```powershell
cd tools/dashboard/ui
npm run dev
```

---

## 6. Database Health & Relational Integrity Validation

Run forensic integrity checks:
```powershell
.\venv\Scripts\python.exe -c "from storage.integrity import DatabaseIntegrityValidator; v = DatabaseIntegrityValidator('market_data.duckdb'); print(v.run_all_checks()); v.close()"
```
