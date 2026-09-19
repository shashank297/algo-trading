# NIFTY-200 PIT Residual Evidence Closure

## Scope and safety

This report is generated from the latest full real-data build. It does not create historical members, promote B1 evidence, certify fuzzy identity matches, weaken validation, run Stage A, or import into DuckDB.

The pre-fix residual baseline is recorded in `reports/nifty200_pit_residual_evidence_baseline_20260919.md`.

## Before → after blocker counts

| Blocker | Before | After | Delta |
| --- | ---: | ---: | ---: |
| DUPLICATE_EVENT | 1 | 2 | 1 |
| MISSING_ANNOUNCEMENT_DATE | 48 | 0 | -48 |
| MISSING_DURABLE_IDENTITY | 0 | 0 | 0 |
| MISSING_INITIAL_ANCHOR | 171 | 134 | -37 |
| MONTHLY_SNAPSHOT_MISSING | 68 | 68 | 0 |
| SOURCE_DOWNLOAD_FAILURE | 1 | 1 | 0 |
| TOTAL_BLOCKER_ROWS | 289 | 205 | -84 |
| CONFLICT_ROWS | 220 | 136 | -84 |

## Current measured build

| Measure | Value |
| --- | ---: |
| Source count | 585 |
| Source hash failures | 0 |
| Event observations | 1544 |
| Canonical events | 671 |
| ADD events | 327 |
| DROP events | 344 |
| Snapshot rows | 21650 |
| Snapshot dates | 108 |
| Valid 200 checkpoints | 58 |
| Missing/non-200 checkpoints | 68 |
| Current security-master rows | 2578 |
| Historical identity rows | 197012 |
| Unique historical instruments | 3874 |
| Durable-ID resolution % | 100.0 |
| ISIN resolution % | 100.0 |
| Unresolved identity count | 0 |
| Constituent intervals | 325 |
| Trading sessions checked | 3613 |
| Minimum active constituents | 0 |
| Maximum active constituents | 118 |
| Sessions not expected | 3613 |
| Known-at unresolved | 0 |
| Conflicts | 136 |
| HIGH conflicts | 1 |
| CRITICAL conflicts | 135 |

## Evidence-resolution results

The parser defect was fixed for official multi-page NIFTY-200 press-release tables, including wrapped rows and a continuation page that restarts numbering for the next action table. Official 2016/2020 rows now enter the canonical chain. No B1 row was promoted.

Source tiers: A1=578, A2=6, B1=1. No new source tier or non-authoritative promotion was introduced by this pass.
Announcement blockers: 48 → 0.
Identity blockers: 0 → 0.
Residual identity cases: 0.
Residual announcement cases: 0.
Non-passing monthly checkpoint rows: 68.
The source-download failure, duplicate OFSS event, initial anchor, and monthly checkpoint gaps remain explicitly unresolved where no free exact A1/A2 evidence closes them.

## Final blockers

Source download failures retained: https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataMay2012.zip.
Duplicate events retained for manual review: 2022-03-31 ABBOTINDIA; 2024-03-28 OFSS.
- `DUPLICATE_EVENT`: 2 rows
- `MISSING_INITIAL_ANCHOR`: 134 rows
- `MONTHLY_SNAPSHOT_MISSING`: 68 rows
- `SOURCE_DOWNLOAD_FAILURE`: 1 rows

## Final status

NIFTY-200 PIT RECONSTRUCTION: DATA EVIDENCE BLOCKED

INDEPENDENT QA: NOT ASSERTED

CAMPAIGN STAGE A: BLOCKED
