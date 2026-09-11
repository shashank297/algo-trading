# NIFTY-200 PIT forensic closure report

Build scope: actual historical NIFTY 200 / CNX 200, 2012-01-02 through 2026-08-20.
The build ran in the isolated delivery worktree and did not touch `market_data.duckdb`
or its WAL.

## Before to after

The post-PR25 baseline was preserved in `reports/nifty200_pit_post_pr25_baseline_20260911.md`.
The current rebuild retained 359 source records, 1,866 observations, 935 canonical
events, 21,650 snapshot rows, 3,609 NSE sessions, and `BLOCKED` validation. The
real improvement was identity accounting: exact current symbols previously produced
duplicate unresolved aliases. After eliminating those false duplicates, historical
identity rows are 2,654 (2,568 certified current-master rows plus 86 manual-review
historical aliases), unresolved aliases are 86 rather than 371, and durable-ID/ISIN
resolution is 96.7596% rather than 87.3767%.

The checkpoint result did not improve by deletion: all 50 PDFs from April 2016 through
May 2020 contain 201 unique plausible symbols, with no duplicate symbol and no parser-
created header row. The final ZEEL row carries the document disclaimer as continuation
text. These remain source-semantics/manual-review blockers.

## Measured final result

- Branch: `codex/nifty200-pit-final-main`
- HEAD at committed code: `dc0a79e09da092ed75f0c7b5d66ade91c67b6ff0`
- origin/main: `a358ed3c2139f9c364c2b53fc749babc9f136a26`
- Sources: 359 total; A1 358; A2 0; B1 1; source hash failures 0.
- Event observations: 1,866 (ADD 746, DROP 1,084, unclassified 36).
- Canonical events: 935 (ADD 375, DROP 560).
- Snapshot rows: 21,650 across 108 dates; valid 200-member checkpoints 58;
  missing/non-200 monthly checkpoints 118.
- Current security-master rows: 2,568.
- Historical identity rows: 2,654; unique historical instruments 2,568.
- Durable-ID resolution: 96.7596%; ISIN resolution: 96.7596%; unresolved identity aliases: 86.
- Constituent intervals: 316.
- NSE campaign sessions checked: 3,609.
- Replay active-member range: 0..87; sessions not equal to 200: 3,609.
- Known-at unresolved canonical events: 0.
- Conflicts: 914 total; HIGH 539; CRITICAL 373; HIGH/CRITICAL 912.
- Initial validation: `BLOCKED`.
- Final validation: `BLOCKED`.

## Evidence findings

### Initial anchor

No authoritative CNX/NIFTY-200 membership anchor effective on 2012-01-02 was found.
The artifact retains 200 rows from the earliest acquired forward checkpoint as
`NOT_ASSERTED`, `MANUAL_REVIEW`, and `eligible_for_replay=false`; it is not consumed
by interval replay. Required closure evidence is a first-party dated anchor or a
complete first-party event chain proving every member and durable identity.

### Historical identities

The current official `EQUITY_L.csv` exactly certifies current symbols. 86 snapshot
symbols are absent from that current master, including historical/delisted/renamed
symbols such as `ALBK`, `ANDHRABANK`, `CAIRN`, `CMC`, `GMRINFRA`, `HDFC`, `IDFC`,
`MINDTREE`, `RANBAXY`, `TATAGLOBAL`, `TATAMOTORS`, `TATAMTRDVR`, `VIDEOIND`, and
`VIJAYABANK`. No fuzzy or successor inference was promoted. They remain manual-review
rows pending period-valid official historical security masters, ISIN mappings, or
corporate-action lineage.

### Duplicate and conflicting events

The corpus contains 58 `DUPLICATE_ADD` interval conflicts and 23 official same-priority
event conflicts, of which 21 are HIGH/CRITICAL in the validation ledger. Forensics
retain all observation IDs, URLs, hashes, dates, actions, and the required manual
resolution. No assertion was silently discarded.

### Checkpoint requirement

The official launch notice describes semi-annual index review. Repository validation
currently requires monthly 200-member checkpoints. The audit therefore concludes
`PERIODIC_CHECKPOINT_SUFFICIENT_PENDING_GOVERNANCE_APPROVAL`; the validator was not
weakened. The 50 one-row-over checkpoints remain explicitly blocked for manual review.

## Remaining blockers

- 314 missing-initial-anchor conflicts, requiring a dated first-party 2012-01-02 anchor
  or predecessor event evidence.
- 518 unresolved observations lacking durable historical identity/lineage.
- 86 historical snapshot aliases absent from the current security master.
- 58 duplicate-add interval conflicts.
- 21 high/critical official-event conflicts.
- 69 months with no acquired official checkpoint and 50 official checkpoints parsed as
  201 rather than the repository's required 200.
- 3,609 downstream session count failures because the interval chain remains unanchored
  and incomplete.

## Sources contacted

The build used the cached official NSE/Nifty Indices corpus, the official current NSE
security master, and the B1 challenger only as a provisional search index. During the
forensic review the official Nifty media archive and these first-party notices were
reviewed: [CNX 200 launch](https://niftyindices.com/Press_Release/ind_prs18072011.pdf),
[March 2012 review](https://niftyindices.com/Press_Release/ind_prs14032012.pdf),
[September 2012 review](https://niftyindices.com/Press_Release/ind_prs16082012.pdf),
[February 2013 review](https://niftyindices.com/Press_Release/ind_prs13022013.pdf),
[March 2013 corporate-action change](https://niftyindices.com/Press_Release/ind_prs15032013.pdf),
and [April 2013 corporate-action change](https://niftyindices.com/Press_Release/ind_prs11042013.pdf).
Direct PDF retrieval from the archive endpoint timed out in the local CLI, so those
web-reviewed PDFs were not promoted into the hashed local source catalogue.

## Safety and delivery

Dry-run importer result: `REFUSED_AS_DESIGNED`, exit 1, `database_touched=false`.
Independent QA: `NOT_ASSERTED`. `approved_for_import`: not granted. Campaign Stage A
was not run.

Required artifact hashes include:

- `constituent_intervals.parquet`: `f173869afc5fa3af46a7c4dcc766d211ab4a5a3fd71f353f9b34ac4facfb4793`
- `initial_anchor_20120102.parquet`: `672c61d44e90e72318dbbc5eee943afd51ff1765f3f170e71f1938870f9dc7af`
- `historical_instrument_master.parquet`: 2,654 rows; hash `59958a2a56b45aebb548c6b8e8d82c36af834183489471f98c693a990dc7bd33`

The delivery branch contains the implementation and reports. Direct push to protected
`main` was rejected because required status checks are configured; merge must proceed
through the review branch and protected PR flow.
