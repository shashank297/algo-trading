# Phase 2.2 — Certified Multi-Timeframe Data: Implementation Plan

## Tech Stack

- **Language**: Python 3.12+ (matches existing codebase)
- **Data manipulation**: pandas 2.x (existing dependency)
- **Storage**: DuckDB via `storage.duckdb_manager.DuckDBManager` (existing)
- **Hashing**: `hashlib.sha256` (existing pattern)
- **Session boundaries**: `trading_stack.calendars.MarketCalendar` (existing)
- **CLI**: `argparse` via `research.py` (existing pattern)
- **Testing**: `pytest` (existing)
- **Timezone**: `zoneinfo.ZoneInfo` (existing)

## Constitution Compliance

| Principle | Compliance |
|---|---|
| I. Data Integrity | Fail-closed DQ; reject quarantined/untrusted; no silent swallowing |
| II. Event-Driven | Not applicable (data layer, not strategy) |
| III. Concurrency | DuckDB write protected by existing `_write_lock` in DuckDBManager |
| IV. DuckDB Resiliency | All writes go through `DuckDBManager` with retry/backoff |
| V. Cost Accuracy | Not applicable (data layer, not backtest) |
| Security | No secrets; no live routing; no price fabrication |

## Project Structure

### New Files

```
data_platform/
    resampling.py           # SessionBarResampler, DerivedDatasetCertification
    dq_derived.py           # DerivedDQReport, DerivedBarDQCertifier
    provider_verification.py # CrossProviderVerifier, ProviderVerificationReport
storage/migrations/
    016_derived_datasets.sql  # derived_datasets + cross_provider_reconciliations tables
tests/
    test_resampling.py      # All resampling correctness and edge case tests
    test_provider_verification.py  # Cross-provider verification tests
    test_migration_016.py   # Migration schema tests
docs/
    derived_bars.md         # Operator documentation
specs/phase2/2.2-certified-multitimeframe-data/  # This spec directory
```

### Modified Files

```
data_platform/__init__.py       # Export new public API
storage/duckdb_manager.py       # persist_derived_dataset(), persist_reconciliation()
research.py                     # build-derived-bars, verify-market-provider commands
```

## Component Design

### `data_platform/resampling.py`

**Class: `SessionBarResampler`**

Core algorithm:
1. Validate input: non-empty DataFrame, required columns, uniform adjustment basis, uniform symbol+exchange.
2. Reject any rows flagged as quarantined (if quarantine column present).
3. Convert timestamps to IST for session boundary assignment.
4. For each trading date in the input:
   a. Get session bounds from `MarketCalendar.session_bounds(date)`.
   b. Filter bars strictly within `[session_open, session_close)` IST.
   c. Compute bucket index: `floor((bar_ist_minutes - session_open_minutes) / target_minutes)`.
   d. Group by bucket index → aggregate OHLCV (first open, max high, min low, last close, sum volume).
   e. Drop any bucket whose `(bucket_index + 1) * target_minutes > session_minutes` (incomplete trailing bucket).
   f. Compute UTC open timestamp for each complete bucket = `session_open + bucket_index * target_minutes`, converted to UTC.
5. Return sorted list of `ResampledBar`.

**Class: `DerivedDatasetCertification`**

Wraps the lineage metadata + DQ status. Produced by `derive_and_certify()`.

### `data_platform/dq_derived.py`

**Class: `DerivedBarDQCertifier`**

Runs all DQ checks on a resampled DataFrame:
1. Schema: all of {timestamp, open, high, low, close, volume} present.
2. OHLC integrity: vectorized check for each row.
3. Duplicate timestamps.
4. Session alignment: each bar's timestamp (converted to IST) falls inside the declared session.
5. Missing buckets: compute expected count from session minutes ÷ target minutes, compare to actual count.
6. Timestamp monotonicity.

Returns `DerivedDQReport`. If `certified=False`, the caller must not persist the dataset as `CANONICAL_PROMOTED`.

### `data_platform/provider_verification.py`

**Class: `CrossProviderVerifier`**

1. Align primary and secondary bars by timestamp.
2. For each primary bar:
   - If no secondary bar exists for this timestamp: UNAVAILABLE.
   - If `abs((primary_price - secondary_price) / primary_price) ≤ tolerance_pct` for all fields: MATCH or TOLERANCE_MATCH.
   - Otherwise: DISAGREEMENT → emit `DATA_VERIFICATION_WARNING` (logger.warning) or raise if severity=BLOCKING.
3. Persist to `cross_provider_reconciliations`.
4. Never modify primary bars.

### `storage/duckdb_manager.py` additions

- `persist_derived_dataset(certification: DerivedDatasetCertification) -> None`
- `persist_reconciliation(report: ProviderVerificationReport) -> None`
- `get_derived_datasets(symbol, timeframe) -> list[dict]`
- `get_canonical_1m_bars(source_dataset_id) -> pd.DataFrame`

### `research.py` additions

New `--command` choices: `build-derived-bars`, `verify-market-provider`

New args:
- `--source-dataset` (canonical 1m dataset_id)
- `--derived-timeframe` (5m|15m|30m|60m)
- `--primary-provider`
- `--secondary-provider`
- `--verification-severity` (WARNING|BLOCKING)
- `--start-date`, `--end-date`

### Migration 016

```sql
CREATE TABLE IF NOT EXISTS derived_datasets (
    derived_dataset_id    VARCHAR NOT NULL PRIMARY KEY,
    source_dataset_ids    VARCHAR NOT NULL,
    source_content_hashes VARCHAR NOT NULL,
    symbol                VARCHAR NOT NULL,
    exchange              VARCHAR NOT NULL,
    timeframe             VARCHAR NOT NULL,
    adjustment_basis      VARCHAR NOT NULL,
    resampler_version     VARCHAR NOT NULL,
    calendar_version      VARCHAR NOT NULL,
    start_ts              TIMESTAMPTZ NOT NULL,
    end_ts                TIMESTAMPTZ NOT NULL,
    row_count             INTEGER NOT NULL,
    content_hash          VARCHAR NOT NULL,
    dq_status             VARCHAR NOT NULL DEFAULT 'PENDING',
    dq_report_json        VARCHAR DEFAULT '{}',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cross_provider_reconciliations (
    reconciliation_id     VARCHAR NOT NULL PRIMARY KEY,
    symbol                VARCHAR NOT NULL,
    exchange              VARCHAR NOT NULL,
    timeframe             VARCHAR NOT NULL,
    primary_provider      VARCHAR NOT NULL,
    secondary_provider    VARCHAR NOT NULL,
    comparison_version    VARCHAR NOT NULL,
    comparison_date       DATE NOT NULL,
    primary_dataset_id    VARCHAR NOT NULL,
    secondary_dataset_id  VARCHAR,
    total_bars_primary    INTEGER NOT NULL,
    total_bars_secondary  INTEGER,
    bars_match            INTEGER NOT NULL DEFAULT 0,
    bars_tolerance_match  INTEGER NOT NULL DEFAULT 0,
    bars_disagreement     INTEGER NOT NULL DEFAULT 0,
    bars_unavailable      INTEGER NOT NULL DEFAULT 0,
    tolerance_config_json VARCHAR NOT NULL DEFAULT '{}',
    bar_outcomes_json     VARCHAR NOT NULL DEFAULT '[]',
    overall_status        VARCHAR NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

## Verification Plan

### Automated Tests

```powershell
# Phase 2.2 focused tests
.\venv\Scripts\python.exe -m pytest tests/test_resampling.py tests/test_provider_verification.py tests/test_migration_016.py -v

# Full suite (must remain 428+ passed)
.\venv\Scripts\python.exe -m pytest -q

# Static analysis
.\venv\Scripts\ruff.exe check .
.\venv\Scripts\mypy.exe data_platform storage experiments research.py
```

### Manual Verification

- Push to `phase2/2.2-certified-multitimeframe-data` and verify CI green on the exact SHA.
- Confirm 0 regressions in the existing 428 tests.
- Confirm new test count ≥ 30 new tests (covering all scenarios from mission section 9).
