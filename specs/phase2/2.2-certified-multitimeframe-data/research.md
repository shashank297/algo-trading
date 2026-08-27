# Phase 2.2 Research Notes

## Decision: Resampling Strategy

**Decision**: Use pandas `groupby` on session-aligned bucket labels (UTC timestamps floored to the target interval within each trading session) rather than `resample()`.

**Rationale**: `pd.DataFrame.resample()` cannot be made session-boundary-aware without complex anchoring and still bleeds across midnight/pre-market when sessions are not UTC-midnight-aligned. A manual `groupby` on a computed bucket column gives full control over which bars belong to which bucket, trivially handles special sessions, and naturally drops incomplete trailing buckets.

**Alternatives considered**:
- `resample()` with `origin` and `offset`: cannot handle non-uniform special session windows without postprocessing.
- Custom Cython extension: overkill for the required bar counts.

## Decision: Derived Dataset Storage

**Decision**: Store derived bar rows in the existing `historical_candles` table, identified by a dedicated `derived_dataset_id` column. Register metadata in a new `derived_datasets` table.

**Rationale**: Reusing `historical_candles` means all existing query infrastructure (backtest data loading, walk-forward slicing) can use derived bars with zero changes. The `derived_dataset_id` field already exists in the lineage chain. A separate `derived_datasets` registry table provides the metadata layer.

**Alternatives considered**:
- Dedicated `derived_candles` table: adds complexity to all consumers.
- Embedded metadata in `market_datasets` with a `dataset_type` discriminator: conflates raw/canonical/derived lifecycle in one table.

## Decision: Session Boundary Algorithm

**Decision**: For each 1m bar, compute its bucket label as:
1. Convert UTC timestamp to IST (`Asia/Kolkata`).
2. Compute `floor(IST_minutes_since_session_open / target_minutes)` to get bucket index.
3. Bucket label = session_date + bucket_index. Only bars where IST time is within [session_open, session_close] are included.
4. A bucket is complete if it contains exactly `target_minutes / 1` source bars or if it ends at or before `session_close`.

**NSE session**: 09:15–15:30 IST = 375 minutes.
- 5m: 75 complete buckets per session
- 15m: 25 complete buckets
- 30m: 12 complete buckets + 1 partial (375 / 30 = 12.5 → 12 complete)
- 60m: 6 complete buckets + 1 partial (375 / 60 = 6.25 → 6 complete)

Incomplete trailing buckets are always dropped (never emitted as partial bars).

## Decision: Content Hash Algorithm

**Decision**: Use `SHA256(JSON canonical representation of sorted OHLCV rows)` — same pattern as `compute_raw_provider_hash` in `data_platform/contracts.py`.

**Rationale**: Consistent with existing lineage hash patterns. JSON canonical form (sort_keys=True, separators=(',',':')) ensures determinism across Python versions.

## Decision: Cross-Provider Verification — No Blending

**Decision**: A DISAGREEMENT between providers emits `DATA_VERIFICATION_WARNING` and records the disagreement to `cross_provider_reconciliations`. The primary data is never touched.

**Rationale**: Blending providers (averaging prices) introduces phantom prices that never existed in the market. This is constitutionally prohibited by the "Never fabricate prices" invariant.

**Tolerance defaults**:
- Price fields (open, high, low, close): relative tolerance ≤ 0.0001 (0.01%)
- Volume: exact match (tolerance = 0) by default, configurable to allow rounding differences

## Decision: DQ Certification — Fail Closed

**Decision**: Any DQ check failure marks the derived dataset as `DQ_FAILED` and prevents it from being stored as `CANONICAL_PROMOTED`. The calling code must not use an uncertified derived dataset for research.

**Rationale**: Constitution principle I: "Never silently swallow bad data."

## Decision: Resampler Version

**Decision**: Embed version string `"session-resampler-v1"` in derivation metadata. Increment on any behavioral change.

## Decision: New Migration 016

**Decision**: Add `storage/migrations/016_derived_datasets.sql` creating:
- `derived_datasets` table (metadata + lineage)
- `cross_provider_reconciliations` table (provider comparison records)

This follows the established sequential migration numbering (015 is the last Phase 2.1 migration).

## Decision: CLI Integration

**Decision**: Add `build-derived-bars` and `verify-market-provider` as `--command` choices in `research.py` (consistent with existing pattern).

New CLI args:
- `--source-dataset` (dataset_id of the canonical 1m source)
- `--derived-timeframe` (5m, 15m, 30m, 60m)
- `--primary-provider` (for cross-provider verification)
- `--secondary-provider` (for cross-provider verification)
- `--verification-severity` (WARNING or BLOCKING)
- `--start-date` / `--end-date` (ISO date strings)
