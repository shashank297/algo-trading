# NIFTY-200 PIT evidence-gap closure report

## Measured final build

- Branch: `codex/nifty200-pit-2012-anchor`
- Build timestamp: `2026-09-17T17:28:28Z` (UTC)
- Campaign: `2012-01-02` through `2026-08-20`
- Sources: 570 total (`A1=565`, `A2=4`, `B1=1`); source-hash errors: 0
- Event observations: 1,583; canonical events: 729 (`ADD=364`, `DROP=365`)
- Monthly snapshot rows: 21,650 across 108 snapshot dates
- Valid 200-member checkpoints: 58; missing/non-200 campaign months: 68
- Current security-master rows: 2,568
- Historical identity rows: 22,925; unique historical instruments: 3,444
- Durable-ID and ISIN resolution: 98.4937%; unresolved event identities: 18
- Constituent intervals: 357
- Trading sessions checked: 3,613; active-count range: 2..124; sessions not at expected count: 3,613
- Known-at unresolved canonical events: 0
- Conflicts: 125 (`HIGH/CRITICAL=125`)
- Authoritative checkpoint replay: 0 matches, 108 mismatches
- Diagnostic reverse-anchor checkpoint sets: 108 matches, 0 mismatches; this diagnostic is not authoritative and is not consumed
- Automated validation: `BLOCKED`

The additional A2 source in this iteration is the archived official NSE file
`https://web.archive.org/web/20140122091713id_/http%3A%2F%2Fnseindia.com%2Fcontent%2Findices%2Find_cnx200list.csv`,
retrieved as 200 equity rows with 200 unique symbols and 200 unique ISINs. Its
content SHA-256 is
`840b495e70121b6e3c3323f78b33e7b62018abd8f459263418dbf07403786084`.
It improves historical identity coverage but is dated 2014-01-13 and therefore
does not establish the 2012-01-02 initial membership anchor.

## Blocker classification

The machine-readable ledger is `artifacts/nifty200_pit_v1/blocker_ledger.csv`.
Its 3,846 rows are composed of:

- 3,613 `COUNT_NOT_200` session failures. The interval set has no certified initial member set, so the validator correctly fails closed on every campaign session.
- 108 `REPLAY_SNAPSHOT_MISMATCH` rows. These are the authoritative interval-vs-checkpoint comparisons; they are a consequence of the missing starting set and incomplete membership-history chain, not permission to promote the reverse candidate.
- 122 `MISSING_MEMBERSHIP_HISTORY` conflict rows. These are official removals for which the corpus has no earlier certified add or initial-member assertion.
- 1 aggregate monthly coverage conflict covering 68 campaign months without an official checkpoint matching the historical count rule.
- 1 `MISSING_INITIAL_ANCHOR` conflict for 2012-01-02.
- 1 `CALENDAR_NOT_CERTIFIED` conflict because the repository calendar has evidenced overrides but not a complete official 2012–2026 session audit.

The exact unresolved rows, dates, symbols, sources, hashes, and required actions remain in `unresolved_gaps.csv`, `replay_checkpoint_differences.csv`, and the ledger; no synthetic member, event, date, identity, or approval was added.

## Changes made in this iteration

- Fixed official PDF row parsing for digit-leading symbols such as `360ONE`; added a regression test and the real corpus now contains the recovered event.
- Added support for official NSE UDiFF bhavcopy identity files after the July 8, 2024 legacy-format discontinuation; added parser and URL-selection regressions.
- Added exact CESC old/new ISIN continuity using an issuer certificate and dated NSE evidence; the historical-ISIN blocker for that transition is cleared.
- Preserved listing-date provenance in historical identity output without treating a current security master as a complete historical master.
- Populated `event_date_snapshots.parquet` as an explicitly labelled event-date evidence index. It contains 729 rows and is not a membership snapshot or anchor.
- Added an unambiguous `replay_checkpoint_difference_count` validation metric.
- Added a parser for the archived official CNX 200 constituent CSV, preserving A2 provenance and date-only validity; added regression tests for valid and invalid rows.

## Remaining free-evidence closure work

1. Acquire a first-party, dated CNX/NIFTY-200 membership list effective on or before 2012-01-02, or prove a complete first-party event chain back to that date. The official launch notice establishes methodology and launch date but contains no member list.
2. For each `MISSING_MEMBERSHIP_HISTORY` row, find the preceding official add/initial-membership assertion or a dated official checkpoint that establishes membership before the removal.
3. Retrieve and classify the 68 missing monthly checkpoint months. A valid source must be parsed and hash-bound; a B1 reconstruction or current constituent list cannot close this gap.
4. Reconcile each of the 108 authoritative checkpoint differences after the anchor and event-history evidence is repaired.
5. Complete an official NSE trading-session audit for the full campaign range, including holidays and special sessions.

Until those evidence requirements are met, the interval parquet is useful for audit/research development only and remains ineligible for authoritative import.
