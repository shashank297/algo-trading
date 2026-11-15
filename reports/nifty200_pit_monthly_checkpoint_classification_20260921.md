# NIFTY-200 Monthly Checkpoint Classification

Date: 2026-09-21  
Branch: `codex/nifty200-pit-authoritative-evidence`  
Local commit before this report: `b1c5bee`

## Scope and denominator

The required classification denominator is exactly 68 campaign months:
2012-01 through 2013-03 (15) and 2022-04 through 2026-08 (53).
The live blocker ledger contains 67 date-bound monthly rows plus one
aggregate `COVERAGE_GAP` conflict row (`c66a6758ca70c090ac661ea9d6bffe0a1671c9e80edaa1a86613f84ab8673572`); the aggregate row
is preserved but is not a separate month.

## A-F result

| Class | Count | Months |
| --- | ---: | --- |
| A — authoritative full roster found | 0 | none |
| B — roster exists, acquisition failed | 0 | none |
| C — official event notice only | 16 | 2012-04, 2012-05, 2012-09, 2013-03, 2022-05, 2022-08, 2022-09, 2023-03, 2023-07, 2023-09, 2024-03, 2024-08, 2024-09, 2025-03, 2025-09, 2026-03 |
| D — invalid/error artifact | 11 | 2012-01, 2012-02, 2012-03, 2012-06, 2012-07, 2012-08, 2012-10, 2012-11, 2012-12, 2013-01, 2013-02 |
| E — no evidence of monthly full-roster publication | 41 | 2022-04, 2022-06, 2022-07, 2022-10, 2022-11, 2022-12, 2023-01, 2023-02, 2023-04, 2023-05, 2023-06, 2023-08, 2023-10, 2023-11, 2023-12, 2024-01, 2024-02, 2024-04, 2024-05, 2024-06, 2024-07, 2024-10, 2024-11, 2024-12, 2025-01, 2025-02, 2025-04, 2025-05, 2025-06, 2025-07, 2025-08, 2025-10, 2025-11, 2025-12, 2026-01, 2026-02, 2026-04, 2026-05, 2026-06, 2026-07, 2026-08 |
| F — governance-only requirement | 0 | none |

No complete first-party roster was found for any of the 68 months. No new
source bytes were admitted and no SHA-256 was added by this classification.

## Evidence pattern observed

- The acquired 2013-04 through 2022-03 archive sequence contains complete
  NIFTY-200 checkpoint rows and supplies the 108 passing monthly periods.
- The expected 2012-01 through 2013-03 archive URLs resolve locally to the
  same invalid HTML response rather than ZIP bytes. Months with an A1/A2
  press/reconstitution notice are class C; months without one are class D.
- The 2022-04 through 2026-08 exact archive URLs are valid official ZIPs, but
  their members are selected indices such as NIFTY 50, NIFTY Bank, NIFTY
  Financial Services, NIFTY Midcap Select, NIFTY IT, NIFTY Next 50, and NIFTY
  India FPI 150. No NIFTY-200/CNX-200 member file was found. Months with an
  official event notice are class C; the remaining months are class E because
  the existence of a separate historical NIFTY-200 roster remains unproven.
- Official press/reconstitution notices are not treated as full monthly
  rosters. B1 is not used as authority.

The exact archive URLs, local hashes, archive member names, event URLs, and
month-by-month chain diagnostics are in the CSV beside this report.

## Event-chain diagnostic

The earliest missing block has no previous authoritative complete checkpoint
and ends at the 2013-04 checkpoint. The later block starts after the
2022-03 checkpoint and has no later authoritative complete checkpoint in the
campaign. Therefore every missing month has `event_chain_complete=NO`,
`identity_coverage_complete=NO`, and `exact_checkpoint_reconciliation_possible=NO`.
The replay set counts in the CSV are diagnostic only and are not promoted to
monthly authority.

## Governance assessment

`INSUFFICIENT_EVIDENCE_TO_CHANGE_CONTRACT`

The evidence shows an observable publication-model boundary: complete monthly
NIFTY-200 files are present in the older acquired archive sequence, while the
later exact archive URLs contain other indices only. That is not sufficient to
prove that no separate NIFTY-200 historical product existed, nor is the
event/identity chain complete enough to support a replacement certification
contract. The current monthly checkpoint contract therefore remains unchanged
and validation remains fail-closed.

No governance code, validator, anchor, identity blocker, calendar blocker,
duplicate-event blocker, May-2012 download, database, or WAL was modified in
this classification task.

## First-party facilities searched

- [NSE Nifty 200 index page](https://www.nseindia.com/static/products-services/indices-nifty200-index) (current constituent download/current-only page).
- [NSE historical Capital Market reports](https://www.nseindia.com/resources/historical-reports-capital-market-daily-monthly-archives).
- [NSE historical index data](https://betansearchives.nseindia.com/reports-indices-historical-index-data).
- [Nifty Indices historical reports](https://niftyindices.com/reports).
- Nifty Indices press-release archive and the exact month event notices in the existing A1 corpus.
- Exact `indices_data<Mon><Year>.zip` URLs and Wayback candidates for each missing month.

## Status

This report classifies the evidence gaps; it does not close them. The PIT
reconstruction remains `DATA EVIDENCE BLOCKED`, independent QA remains
`NOT_ASSERTED`, import approval remains not granted, and no push or merge was
performed.
