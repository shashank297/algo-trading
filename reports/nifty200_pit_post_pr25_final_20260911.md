# NIFTY-200 PIT post-PR25 final empirical report

- Build scope: 2012-01-02 through 2026-08-20; NSE calendar: `nse-pandas-market-calendars`.
- Build worktree HEAD: `915afa8dca7a44097842f83917b6dc0619c5d2c1`; origin/main at verification: `a358ed3c2139f9c364c2b53fc749babc9f136a26`.
- Sources: 359 total (A1 358, A2 0, B1 1); source hash failures 0.
- Event observations: 1,866 (ADD 746, DROP 1,084, unclassified 36); canonical events 935 (ADD 375, DROP 560).
- Monthly snapshots: 21,650 rows across 108 dates; 58 source checkpoints parsed at exactly 200 members; 118 monthly gaps remain (68 missing-source months, 50 parsed 201-member months).
- Current security master: 2,568 rows; historical identity table: 2,568 current-listing anchors; unique instruments 2,568; durable-ID and ISIN resolution 87.3767%; unresolved identities 371.
- Constituent intervals: 316. Replayed 3,609 NSE sessions; active-member range 0..87; sessions not equal to 200: 3,609.
- Known-at audit: 935 rows; known-at unresolved 0.
- Conflicts: 913 total (HIGH 539, CRITICAL 372, MEDIUM 2). Ledger: 4,638 rows: COUNT_NOT_200 3,609; MISSING_DURABLE_IDENTITY 517; MISSING_INITIAL_ANCHOR 314; DUPLICATE_EVENT 58; CONFLICTING_OFFICIAL_EVENTS 21; MONTHLY_SNAPSHOT_MISSING 69; MONTHLY_SNAPSHOT_NOT_200 50.
- Validation: initial `BLOCKED`; final `BLOCKED`. The parser correction removed a PDF-wrapped sector token from the March 2021 checkpoint; no historical membership or identity was fabricated.
- Dry-run importer: refused as designed, exit 1, `database_touched=false`; independent QA `NOT_ASSERTED`; import approval not granted.

## Remaining evidence gaps

- `A_NO_SNAPSHOT_EVIDENCE`: 2012-01 through 2013-03 and 2022-04 through 2026-08. Required evidence: official historical monthly NIFTY/CNX-200 membership checkpoints.
- `B_SNAPSHOT_NON_200`: 2016-04 through 2020-05, each parsed as 201 members. Required evidence: manual audit of the official PDF table and methodology to determine whether the 201st row is a parser artifact or a documented methodology/count condition.
- `MISSING_INITIAL_ANCHOR`: 314 removal-of-absent-member conflicts. Required evidence: an official initial membership anchor and/or the missing predecessor ADD evidence.
- `MISSING_DURABLE_IDENTITY`: 517 unresolved observations and 371 unresolved snapshot aliases. Required evidence: period-valid official historical security masters, ISIN mappings, symbol/name changes, delisting and merger records. The current `EQUITY_L.csv` is not sufficient to certify these historical aliases.
- `DUPLICATE_EVENT`: 58 duplicate ADD assertions. Required evidence: source-level reconciliation and superseding/duplicate-event disposition.
- `CONFLICTING_OFFICIAL_EVENTS`: 21 high/critical same-priority conflicts. Required evidence: authoritative correction or superseding notice.
- `COUNT_NOT_200`: all 3,609 checked sessions fail replay count because the interval chain is not anchored and complete; this is a downstream consequence, not a license to synthesize members.

## Artifact paths

The final package is under `artifacts/nifty200_pit_v1/`. The blocker ledger, unresolved gaps, validation report, evidence manifest, and interval parquet are the corresponding required files in that directory. The monthly and known-at reports are under `reports/`.

## Free evidence contacts

The official current NSE `EQUITY_L.csv` endpoint returned HTTP 200 and was hashed into the corpus. The live Nifty Indices press-release page timed out; the Wayback CDX query returned HTTP 503. Official Nifty 200 methodology/report pages and NSE historical-data documentation were reviewed, but no free historical official security-master archive sufficient to certify the unresolved aliases was found.
