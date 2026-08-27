# Phase 2.2 — Quickstart Validation Guide

## Prerequisites

- Phase 2.1 merged and green on `main`
- Working on branch `phase2/2.2-certified-multitimeframe-data`
- `market_data.duckdb` reachable with at least some canonical 1m bars for a test symbol

## Run Phase 2.2 Focused Tests

```powershell
# From repo root
.\venv\Scripts\python.exe -m pytest tests/test_resampling.py tests/test_provider_verification.py tests/test_migration_016.py -v
```

Expected: All Phase 2.2 tests pass.

## Run Full Test Suite

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

Expected: 428+ passed (original suite) + Phase 2.2 tests, 0 failures.

## Validate Migration

```powershell
.\venv\Scripts\python.exe -c "
from storage.duckdb_manager import DuckDBManager
db = DuckDBManager(':memory:')
tables = db.conn.execute(\"SELECT table_name FROM information_schema.tables WHERE table_name IN ('derived_datasets', 'cross_provider_reconciliations')\").fetchall()
print('Tables:', [t[0] for t in tables])
"
```

Expected output: `Tables: ['derived_datasets', 'cross_provider_reconciliations']`

## Validate Resampler (Unit Smoke Test)

```python
import pandas as pd
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from data_platform.resampling import SessionBarResampler
from trading_stack.calendars import MarketCalendar
from trading_stack.domain import infer_market_spec

# Build 375 synthetic 1m bars for 2024-01-02 NSE session (9:15–15:30 IST)
tz = ZoneInfo("Asia/Kolkata")
session_start = datetime(2024, 1, 2, 9, 15, tzinfo=tz)
bars = []
for i in range(375):
    ts = session_start + pd.Timedelta(minutes=i)
    bars.append({"timestamp": ts.astimezone(timezone.utc), "open": 100+i, "high": 101+i, "low": 99+i, "close": 100.5+i, "volume": 1000})
df = pd.DataFrame(bars)

spec = infer_market_spec("RELIANCE", "NSE")
cal = MarketCalendar(spec)
resampler = SessionBarResampler()
result_5m = resampler.resample(df, "5m", cal, "SPLIT_ADJUSTED")
print(f"5m bars: {len(result_5m)}")   # Expected: 75
result_15m = resampler.resample(df, "15m", cal, "SPLIT_ADJUSTED")
print(f"15m bars: {len(result_15m)}")  # Expected: 25
result_30m = resampler.resample(df, "30m", cal, "SPLIT_ADJUSTED")
print(f"30m bars: {len(result_30m)}")  # Expected: 12
result_60m = resampler.resample(df, "60m", cal, "SPLIT_ADJUSTED")
print(f"60m bars: {len(result_60m)}")  # Expected: 6
```

## Validate Cross-Provider Verification (No Blending)

```python
import pandas as pd
from data_platform.provider_verification import CrossProviderVerifier, VerificationSeverity
from storage.duckdb_manager import DuckDBManager

# Build two matching datasets
from datetime import datetime, timezone
bars = [{"timestamp": datetime(2024, 1, 2, 3, 45, tzinfo=timezone.utc), "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000}]
primary = pd.DataFrame(bars)
secondary = pd.DataFrame(bars)  # exact match

db = DuckDBManager(":memory:")
verifier = CrossProviderVerifier()
report = verifier.verify(primary, secondary, "RELIANCE", "NSE", "5m", "angel_one", "nse_feed",
                         VerificationSeverity.WARNING, None, db)
print(f"MATCH: {report.bars_match}")  # Expected: 1
assert primary.equals(pd.DataFrame(bars)), "Primary MUST NOT be modified by verification"
print("No blending invariant: PASS")
```

## CLI Smoke Tests (after implementation)

```powershell
# Build derived bars
.\venv\Scripts\python.exe research.py --command build-derived-bars \
    --symbol RELIANCE --source-dataset <dataset_id> --derived-timeframe 15m

# Verify market provider
.\venv\Scripts\python.exe research.py --command verify-market-provider \
    --symbol RELIANCE --timeframe 5m \
    --primary-provider angel_one --secondary-provider nse_feed \
    --start-date 2024-01-01 --end-date 2024-01-31
```
