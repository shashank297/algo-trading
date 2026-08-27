# Certified Multi-Timeframe Data Platform (Phase 2.2)

## Overview

The **Certified Multi-Timeframe Data Platform** extends the canonical market-data layer with session-aware derived bars (5m, 15m, 30m, 60m) and observational cross-provider reconciliation while strictly preserving lineage and preventing synthetic data blending.

---

## 1. Resampling Engine & Invariants

The `SessionBarResampler` (`data_platform/resampling.py`) aggregates canonical, certified 1-minute bars into higher-timeframe bars subject to strict safety invariants:

- **Session Awareness**: Resampling never crosses NSE session boundaries (09:15–15:30 IST) or combines different trading days.
- **Complete Source Evidence**: Every emitted N-minute bucket contains exactly N consecutive valid 1-minute observations. Interior gaps, duplicate/misaligned minutes, invalid numerics, or an untrusted source fail closed. Only the unavoidable trailing partial session bucket is dropped.
- **Authoritative OHLCV Aggregation**:
  - `open`: First authoritative open price in bucket.
  - `high`: Maximum authoritative high price in bucket.
  - `low`: Minimum authoritative low price in bucket.
  - `close`: Last authoritative close price in bucket.
  - `volume`: Sum of all authoritative volumes in bucket.
- **No Forward-Filling / Synthetic Prices**: Gaps are not synthetic or forward-filled.
- **Fail-Closed Guards**: Rejects mixed adjustment basis, mixed symbol/exchange identities, and quarantined/untrusted source intervals.

---

## 2. Lineage & Reproducibility

Every derived dataset records complete provenance in the `derived_datasets` DuckDB table:

- `derived_dataset_id`: Unique identifier (e.g. `derived_RELIANCE_5m_20240102_...`).
- `source_dataset_ids`: JSON array of parent canonical 1m dataset IDs.
- `source_content_hashes`: JSON array of parent dataset SHA-256 hashes.
- `timeframe`: Derived timeframe (`5m`, `15m`, `30m`, `60m`).
- `resampler_version`: e.g. `session-resampler-v1`.
- `calendar_version`: e.g. `builtin-v1`.
- `adjustment_basis`: e.g. `SPLIT_ADJUSTED`.
- `row_count`: Number of certified derived bars.
- `content_hash`: SHA-256 hash computed deterministically over the derived bar sequence and exact source identity/hash, requested range, adjustment, calendar, resampler version, and timeframe.
- `dq_status`: `CERTIFIED` or `DQ_FAILED`.

Resampling is completely deterministic: identical source data + calendar + resampler version + timeframe reproduces the identical content hash.

---

## 3. Data Quality (DQ) Certification

The `DerivedBarDQCertifier` (`data_platform/dq_derived.py`) executes 6 validation gates on all resampled bars:

1. **Schema Check**: Validates required columns (`timestamp`, `open`, `high`, `low`, `close`, `volume`) and types.
2. **OHLC Integrity**: Enforces `low <= min(open, close)` and `high >= max(open, close)` with positive prices and volumes.
3. **No Duplicates**: Strict uniqueness on timestamps.
4. **Session Alignment**: Enforces that all bars start and end within valid market sessions.
5. **Monotonicity**: Strict chronological timestamp ordering.
6. **Completeness / Missing Buckets**: Audits gaps against expected session buckets.

Certification fails closed: any integrity violation creates durable `DQ_FAILED` forensic lineage evidence, writes no authoritative candles, and halts pipeline admission. A certified result is atomically registered in `historical_candles`, `derived_datasets`, `market_datasets`, and the authoritative DQ ledger.

---

## 4. Cross-Provider Verification (No Blending Invariant)

The `CrossProviderVerifier` (`data_platform/provider_verification.py`) provides observational verification between primary and secondary providers:

- **Primary Provider**: Remains canonical and untouched.
- **Secondary Provider**: Purely observational comparison.
- **No Blending Invariant**: Primary data is NEVER averaged, interpolated, or blended with secondary data (i.e. `(primary + secondary)/2` is strictly forbidden).
- **Per-Bar Outcomes**:
  - `MATCH`: Exact match across all OHLCV fields.
  - `TOLERANCE_MATCH`: Relative difference within configured tolerance (default 0.01% price).
  - `DISAGREEMENT`: Difference exceeds tolerance.
  - `UNAVAILABLE`: Secondary bar missing for given timestamp.
- **Severity Modes**:
  - `WARNING`: Issues `DATA_VERIFICATION_WARNING` and logs reconciliation details.
  - `BLOCKING`: Persists the complete reconciliation first, then raises `ProviderDataVerificationError` to block research admission.

Reconciliation summaries and per-bar audits are persisted to `cross_provider_reconciliations`.

---

## 5. CLI Commands

### Build Derived Bars
```powershell
.\venv\Scripts\python.exe research.py --command build-derived-bars \
    --source-dataset ds_canonical_1m_reliance \
    --symbol RELIANCE \
    --timeframe 5m \
    --start-date 2024-01-02 --end-date 2024-01-02
```

### Verify Cross-Provider Reconciliation
```powershell
.\venv\Scripts\python.exe research.py --command verify-market-provider \
    --symbol RELIANCE \
    --timeframe 5m \
    --primary-provider angel_one \
    --secondary-provider nse_feed \
    --primary-dataset ds_canonical_5m_reliance \
    --secondary-dataset ds_observational_5m_reliance \
    --start-date 2024-01-02 --end-date 2024-01-02 \
    --verification-severity WARNING
```
