# Research: Platform Hardening & Ingestion Resilience

## Decisions & Rationale

### 1. Shared RateLimiter Architecture
- **Decision**: Allow `HistoricalDataClient.__init__` to accept an optional `rate_limiter: RateLimiter | None = None`. If provided, it reuses the shared instance; otherwise it creates a local one.
- **Rationale**: `backfill_market_history.py` can create one top-level `RateLimiter(rps=3, rpm=180)` and pass it into each thread's `HistoricalDataClient`. Thread safety is already built into `RateLimiter` via `self._lock = threading.Lock()`.
- **Alternatives considered**: Global module-level singleton (less testable, complicates mocking in unit tests).

### 2. Dashboard Strategy Aggregation Fix
- **Decision**: In `tools/dashboard/api/main.py:get_strategies`, change the symbol count calculation to:
  `COUNT(DISTINCT COALESCE(NULLIF(split_part(sr.run_id, ':', 2), ''), sr.symbol, 'PORTFOLIO')) AS total_stocks`
- **Rationale**: If `run_id` has no colons (e.g. `exp-cross_sectional_momentum-1234`), `split_part` returns `""` which is now converted to NULL and falls back to `sr.symbol` or `'PORTFOLIO'`.

### 3. Dynamic API Base URL in Dashboard UI
- **Decision**: Use `const API_BASE = (window as any).__API_BASE__ || import.meta.env?.VITE_API_URL || 'http://localhost:8000/api';` or fallback to relative `/api` if served behind reverse proxy.
- **Rationale**: Avoids network breakage when accessed via alternate hostnames or ports.

### 4. Same-Day Instrument Master Cache
- **Decision**: In `smartapi/instrument.py:download_instrument_master`, check if `data/instrument_master.json` exists and its modification date matches today's date in IST. If valid, log cache hit and load directly unless `force=True`.
- **Rationale**: Saves 150MB network download on every startup.
