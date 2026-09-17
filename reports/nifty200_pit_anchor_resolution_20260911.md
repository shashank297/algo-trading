# NIFTY-200 PIT anchor-resolution closure

Build date: 2026-09-11 UTC  
Branch: `codex/nifty200-pit-2012-anchor`  
Base: `a8f383149187b8d0bbfb23253ba81c464ec8563f`

## Decision

`2012 ANCHOR: NOT YET DEFENSIBLY ESTABLISHED`

The authoritative validator remains fail-closed. No synthetic 2012 membership, predecessor/successor mapping, ISIN, or approval was created.

## Final measured build

- Sources: 361 total; A1=360, A2=0, B1=1; source hash failures=0.
- Event observations: 1,693; ADD=682, DROP=965, unclassified=46.
- Canonical events: 795; ADD=326, DROP=469.
- Monthly snapshots: 21,650 rows across 108 dates, from 2013-04-18 through 2022-03-31.
- Valid 200-member checkpoints: 58.
- Missing/non-200 monthly checkpoints: 118 (68 no-source months, 50 parsed 201-member checkpoints).
- Current NSE security-master rows: 2,568.
- Historical identity rows: 3,057; unique historical instruments: 2,568.
- Certified durable-ID/ISIN resolution: 2,971/3,057 = 97.19%; unresolved identity rows: 86.
- Constituent intervals: 282.
- NSE campaign sessions checked: 3,609; replay range=0..97; sessions not equal to 200=3,609.
- `known_at` unresolved: 0.
- Conflicts: 874 total; HIGH=561; CRITICAL=311; MEDIUM=2.
- Validation: `BLOCKED`.

## Remaining evidence blockers

The blocker ledger contains 4,599 typed rows:

- 3,609 `COUNT_NOT_200`: the event chain has no certified initial 200-member set, so replay cannot establish 200 members on any campaign session.
- 553 `MISSING_DURABLE_IDENTITY`: 86 distinct identity candidates remain manual review; the ledger records each observation/date and source provenance.
- 268 `MISSING_INITIAL_ANCHOR`: removals cannot be applied to an inactive instrument without a certified starting state.
- 68 `MONTHLY_SNAPSHOT_MISSING`: no official checkpoint was acquired for those campaign months.
- 50 `MONTHLY_SNAPSHOT_NOT_200`: the acquired official checkpoint parses to 201 rows and requires source/methodology review.
- 43 `DUPLICATE_EVENT`: the source chain asserts an add for an already-active instrument.
- 7 `CONFLICTING_OFFICIAL_EVENTS`: same-priority official evidence disagrees; these remain fail-closed.

The exact security/date/source rows are in `artifacts/nifty200_pit_v1/blocker_ledger.csv`; the identity-level unresolved set is in `instrument_resolution_report.csv` and `historical_identity_resolution.csv`. The monthly distinction is in `monthly_gap_analysis.csv`.

## Remediation applied

- Bounded PDF extraction to the numbered CNX/NIFTY-200 section so neighboring index tables are not mixed into NIFTY-200 events.
- Propagated explicit effective dates from matching official A1 release/event rows for releases whose native PDF text is column-interleaved.
- Harvested the official NSE `symbolchange.csv` and used it only for unique, period-bounded historical aliases; ambiguous aliases remain manual review.
- Accepted compact official PDF rows without serial numbers and normalized PDF layout splits such as `ORCHIDCHE M` to `ORCHIDCHEM`.

Compared with the saved post-PR25 baseline, the stricter parser removed false event rows while the identity/date fixes increased the diagnostic replay quality: 58 valid checkpoints are now recognized, up from 46; the current official event chain has 795 canonical events and 282 intervals.

## Import and governance boundary

- Dry-run importer: refused because validation is not PASS; no database write was attempted.
- Independent QA: `NOT_ASSERTED`.
- Import approval: not granted.
- Campaign Stage A: blocked.

Official evidence consulted includes the Nifty Indices media archive, the CNX-200 launch notice, official NIFTY-200 change PDFs, official NSE `EQUITY_L.csv`, official NSE `symbolchange.csv`, official NSE circular/security-list pages, the acquired official monthly archives, and the B1 challenger dataset used only as a search index.
