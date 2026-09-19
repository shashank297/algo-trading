# NIFTY-200 PIT Residual Evidence Closure

## Scope and safety

This report is generated from the latest full real-data build. It does not create historical members, promote B1 evidence, certify fuzzy identity matches, weaken validation, run Stage A, or import into DuckDB.

The pre-fix residual baseline is recorded in `reports/nifty200_pit_residual_evidence_baseline_20260919.md`.

## Before → after blocker counts

| Blocker | Before | After | Delta |
| --- | ---: | ---: | ---: |
| DUPLICATE_EVENT | 1 | 2 | 1 |
| MISSING_ANNOUNCEMENT_DATE | 48 | 0 | -48 |
| MISSING_DURABLE_IDENTITY | 0 | 30 | 30 |
| MISSING_INITIAL_ANCHOR | 171 | 133 | -38 |
| MONTHLY_SNAPSHOT_MISSING | 68 | 68 | 0 |
| SOURCE_DOWNLOAD_FAILURE | 1 | 1 | 0 |
| TOTAL_BLOCKER_ROWS | 289 | 234 | -55 |
| CONFLICT_ROWS | 220 | 165 | -55 |

## Current measured build

| Measure | Value |
| --- | ---: |
| Source count | 585 |
| Source hash failures | 0 |
| Event observations | 1544 |
| Canonical events | 641 |
| ADD events | 308 |
| DROP events | 333 |
| Snapshot rows | 21650 |
| Snapshot dates | 108 |
| Valid 200 checkpoints | 58 |
| Missing/non-200 checkpoints | 68 |
| Current security-master rows | 2578 |
| Historical identity rows | 197012 |
| Unique historical instruments | 3874 |
| Certified historical identity rows | 192913 |
| Current-snapshot-only identity rows | 2578 |
| Explicit historical-interval identity rows | 187602 |
| Manual-review identity rows | 1521 |
| Historical event identity rows (denominator) | 1544 |
| Certified historical event identity rows | 678 |
| Certified historical event identity resolution % | 43.9119 |
| ISIN resolution % among historical event rows | 43.9119 |
| Unresolved historical event identity cases | 58 |
| Manual-review historical event identity rows | 464 |
| Constituent intervals | 306 |
| Trading sessions checked | 3613 |
| Minimum active constituents | 0 |
| Maximum active constituents | 117 |
| Sessions not expected | 3613 |
| Known-at unresolved | 0 |
| Conflicts | 165 |
| HIGH conflicts | 31 |
| CRITICAL conflicts | 134 |

## Evidence-resolution results

The parser defect was fixed for official multi-page NIFTY-200 press-release tables, including wrapped rows and a continuation page that restarts numbering for the next action table. Official 2016/2020 rows now enter the canonical chain. No B1 row was promoted.

Source tiers: A1=578, A2=6, B1=1. No new source tier or non-authoritative promotion was introduced by this pass.
Announcement blockers: 48 → 0.
Identity blockers: 0 → 30.
Residual identity cases: 30.
Residual announcement cases: 0.
Non-passing monthly checkpoint rows: 68.
## Temporal identity correction

The pre-correction PR #29 report exposed unresolved identity as 0 using its legacy alias-inventory denominator; that was not a strict historical-event measure.
A separate pre-PR #29 strict historical-event baseline was not preserved, so it is not inferred here.
Corrected strict historical-event result: 58 unresolved of 1544 event identity rows; 464 remain manual-review.
Certified historical identity resolution among event rows: 43.9119%; ISIN resolution on the same denominator: 43.9119%.
The source-download failure, duplicate OFSS event, initial anchor, and monthly checkpoint gaps remain explicitly unresolved where no free exact A1/A2 evidence closes them.

## Final blockers

Source download failures retained: https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataMay2012.zip.
Duplicate events retained for manual review: 2022-03-31 ABBOTINDIA; 2024-03-28 OFSS.
- `DUPLICATE_EVENT`: 2 rows
- `MISSING_DURABLE_IDENTITY`: 30 rows
- `MISSING_INITIAL_ANCHOR`: 133 rows
- `MONTHLY_SNAPSHOT_MISSING`: 68 rows
- `SOURCE_DOWNLOAD_FAILURE`: 1 rows

## Final status

NIFTY-200 PIT RECONSTRUCTION: DATA EVIDENCE BLOCKED

INDEPENDENT QA: NOT ASSERTED

CAMPAIGN STAGE A: BLOCKED
