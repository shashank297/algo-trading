# NIFTY-200 PIT Evidence Closure — Current Measured State

## Scope and safety

This report records the current real-data build after the evidence-closure
pass. It does not create historical members, promote B1 evidence, certify
fuzzy identity matches, weaken the checkpoint gate, or import into DuckDB.

The earlier recovery baseline remains preserved in
`reports/nifty200_pit_recovery_closure_20260919.md`. The evidence-enriched
starting point for this pass was 583 sources and 337 blocker rows.

## Current measurements

| Measure | Value |
| --- | ---: |
| Source count | 583 |
| Source hash failures | 0 |
| Event observations | 1496 |
| Canonical events | 593 |
| Snapshot rows | 21650 |
| Snapshot dates | 108 |
| Valid 200 checkpoints | 58 |
| Missing/non-200 checkpoints | 68 |
| Constituent intervals | 261 |
| Trading sessions checked | 3613 |
| Minimum active constituents | 0 |
| Maximum active constituents | 104 |
| Sessions not expected | 3613 |
| Known-at unresolved | 0 |
| Conflicts | 249 |
| HIGH conflicts | 79 |
| CRITICAL conflicts | 170 |

Validation status: **BLOCKED**.

## Remaining blocker classes

- `DUPLICATE_EVENT`: 1 rows
- `MISSING_ANNOUNCEMENT_DATE`: 46 rows
- `MISSING_DURABLE_IDENTITY`: 32 rows
- `MISSING_INITIAL_ANCHOR`: 170 rows
- `MONTHLY_SNAPSHOT_MISSING`: 68 rows
- `SOURCE_DOWNLOAD_FAILURE`: 1 rows

The case CSVs contain one row per current identity or announcement
blocker, including the missing document, official URLs checked, and the
exact condition needed to close it. The monthly governance report keeps
missing, malformed, wrong-table, methodology, and HTML-response cases
separate. The paid fallback file is an audit record only; no paid source
was purchased or used.

## Final disposition

NIFTY-200 PIT RECONSTRUCTION: DATA EVIDENCE BLOCKED

INDEPENDENT QA: NOT ASSERTED

CAMPAIGN STAGE A: BLOCKED
