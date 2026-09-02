# Campaign 1 Data Readiness Recovery

Date: 2026-09-02
Branch: `main`
HEAD: `2d653914799e2c458d01be0b77f978074a1ae1b0`
DuckDB: `1.5.5`

## Decision

Recovery classification: `UNRECOVERABLE_FROM_CURRENT_FILES`.

The original database and matching WAL were preserved. The WAL cannot be replayed by
DuckDB 1.5.5, and its contents include pending provider/schema transactions. A base-only
copy is readable and internally stable, but it is not treated as an authoritative recovery
because removing the WAL can hide committed or pending data loss.

The readable candidates also contain no authoritative historical constituent membership
evidence. Campaign 1 cannot be certified or started from these files.

## Original Files

| Path | Size | SHA-256 |
| --- | ---: | --- |
| `market_data.duckdb` | 9,860,820,992 bytes | `BE513B6E5D0E8ED7C0E70F3EFD58406565DE2CE554F493B81E9B421C409FED0E` |
| `market_data.duckdb.wal` | 2,396 bytes | `CA4E2221286E0F16E7BFBB1FB7050118F0CA883FED28A5BEDB7E1CA7154356DF` |

The original files were not overwritten or deleted.

## Recovery Candidates

Recovery workspace: `recovery/campaign1-20260902/`

| Candidate | Result |
| --- | --- |
| `market_data.duckdb` plus copied `market_data.duckdb.wal` | Read-only open failed twice during WAL replay with `InternalException: Failure while replaying WAL file ... Calling DatabaseManager::GetDefaultDatabase with no default database set`. |
| `base-only/market_data.duckdb` | Read-only open, catalog query, and critical-count query passed twice. This is a forensic candidate only; the WAL was not deleted from the original. |
| `recovered-authoritative/market_data.duckdb` | Isolated migration/checkpoint probe applied migrations 014 and 018, then failed at migration 019 with `InternalException: BoundIndex::CreateDeltaIndex is not supported for this index type`. This copy is not authoritative. |

Readable backup manifest:

- `backups/market_data-20260818.duckdb`: 4,053,020,672 bytes, SHA-256
  `498DEAE820657C27992D3B623B76581D5394A838C311CB5B758068508DD812E9`.
- Manifest created `2026-08-18T00:22:36.541054+00:00`.
- Manifest counts: `experiments=626`, `historical_candles=24431417`,
  `market_datasets=3185`, `strategy_runs=221`, `table_count=48`.
- `backups/restore-drill-20260818.duckdb` was also readable with the same recorded size;
  it was used as a recovery candidate, not as a substitute for PIT evidence.

## Commands And Outcomes

The following checks were run against copies or in read-only mode:

1. `duckdb.connect("market_data.duckdb", read_only=True)` — failed during WAL replay.
2. The copied DB/WAL pair in `recovery/campaign1-20260902/` — failed identically on two
   independent opens.
3. Two independent read-only opens of
   `recovery/campaign1-20260902/base-only/market_data.duckdb` — passed with stable catalog,
   counts, timestamps, and duplicate checks.
4. `tools/database_recovery.py verify --backup recovery/campaign1-20260902/base-only/market_data.duckdb`
   — passed: 75 tables; `experiments=600`, `historical_candles=62372402`,
   `market_datasets=4874`, `strategy_runs=200`.
5. `tools/database_recovery.py verify --backup backups/market_data-20260818.duckdb` —
   passed using the recorded backup manifest.
6. Focused PIT/universe tests:
   `python -m pytest tests/test_causality_and_invariants.py -k "pit or survivorship or universe" -q`
   — `4 passed, 32 deselected`.

The copied WAL contains readable references to `provider_attempts`, `market_data`,
`market_datasets`, `historical_candles`, `index_constituents_pit`, and schema migrations,
including a failed `angel_one` request for `SHRIRAMFIN-EQ`. This is why the WAL is treated
as potentially material rather than silently discarded.

## Market Data Inventory

The base-only candidate contains 62,372,402 historical candles and 4,874 market datasets.
Coverage by venue/timeframe is:

| Timeframe | Venue | Rows | Symbols | Earliest | Latest |
| --- | --- | ---: | ---: | --- | --- |
| `1d` | `BSE` | 4 | 1 | `2025-06-16` | `2025-10-29` |
| `1d` | `NSE` | 615,404 | 201 | `2012-01-02` | `2026-08-20` |
| `1m` | `BSE` | 9 | 1 | `2025-06-16 11:16` | `2025-10-29 13:05` |
| `1m` | `NSE` | 61,756,985 | 201 | `2015-12-01 09:15` | `2026-08-20 10:46` |

All 4,874 dataset records report `VALID`. The critical candle duplicate-key check returned
zero duplicates. These facts establish market-data integrity for the candidate, not PIT
eligibility.

## Universe And PIT Inventory

The base-only candidate has 75 tables and an `index_constituents_pit` table, but its row
count is zero. It has one universe snapshot:

- ID: `NIFTY200_2026_08_17`
- Members: 200
- `active_from`: `2026-08-17` for all members
- `active_to`: absent for all members
- `survivorship_bias`: `true`
- Historical additions, removals, former constituents, and delistings: unavailable.

The readable backup has 48 tables, no `index_constituents_pit` table, and the same
survivorship-biased current snapshot shape. Repository support in
`data_platform/universe.py` and migrations proves that PIT storage is supported by the
schema; it does not prove that historical membership records exist.

The current snapshot is therefore rejected as historical PIT evidence. Adversarial checks
for additions, removals, future-event mutation, and date-specific reconstruction cannot
pass when the authoritative membership-event set is empty.

## Coverage And Certification

The campaign-safe intersection

`market data coverage ∩ PIT coverage ∩ certification coverage`

is unavailable because PIT coverage is empty and no historical constituent certification
exists. The campaign-safe date range is `NONE`.

The base-only candidate contains zero rows in each of:

- `research_frame_certifications`
- `data_quality_certifications`
- `run_certifications`
- `run_certification_bundles`

Operational `quality_report` rows exist, but they do not establish historical constituent
lineage or replace the required certification artifacts.

## Campaign Baseline Protection

No production source, schema, economic assumption, strategy code, Phase 2.8-2.10 runtime
behavior, or `trading_stack/selector.py` was changed. `research.live_trading` remains
`false`. No Stage A, Stage B, or experiment was started. The Campaign 1 baseline remains
unmodified and uncertified.

## Remaining Blockers

1. `UNRECOVERABLE_FROM_CURRENT_FILES`: the original DB/WAL pair cannot be replayed, and
   the base-only candidate cannot be certified as a complete authoritative recovery.
2. `EXTERNAL HISTORICAL CONSTITUENT DATA REQUIRED`: no authoritative historical PIT
   membership evidence is present in the readable candidates.
3. Campaign-safe coverage and certification cannot be computed without PIT history and
   corresponding lineage/certification artifacts.
4. The isolated migration probe fails at migration 019; this remains a recovery/tooling
   blocker and was not allowed to mutate the originals.

CAMPAIGN 1 DATA READINESS BLOCKED
