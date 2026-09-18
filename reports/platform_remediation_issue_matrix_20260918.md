# Platform and NIFTY-200 PIT remediation issue matrix

Generated from the real local rebuild on 2026-09-18 and re-verified after the
platform remediation pass. This is an evidence and software-remediation status
report, not an approval or independent QA report.

## Current build

- Branch: `codex/platform-audit-remediation-clean`
- HEAD: `a8f383149187b8d0bbfb23253ba81c464ec8563f`
- Build ID: `c5cdfb742fe79ce85cc6025a3da89497164e6f6b622a7cb89729a30271ca5da4`
- Artifact status: `BLOCKED`
- Independent QA: `NOT_ASSERTED`
- Import approval: `NOT_GRANTED`
- Production database/WAL: not touched

## Latest post-remediation rebuild

- Rebuild command: `python -m tools.nifty200_pit.build_public_dataset`
- Build ID: `749a931d7708afdaebb824f79eecc49fc882f5c64c97825667ccf3ff80848585`
- Code execution ID: `UNCOMMITTED:3f79606bcd13bd2910716f5b367459ac2dbd91f71a0ebdc8631b0b1160aac4e6`
- Source records: 362 (`A1=361`, `A2=0`, `B1=1`); source hash failures: 0
- Event observations: 1,866; canonical events: 871 (`ADD=352`, `DROP=519`)
- Monthly snapshots: 21,650 rows across 108 dates; 58 valid 200-member checkpoints,
  68 missing checkpoints, and 50 non-200 checkpoints
- Current security-master rows: 2,568; historical identity rows: 6,886;
  unique historical instruments: 2,568; durable-ID/ISIN resolution: 43.2906%;
  unresolved identity: 3,364
- Constituent intervals: 293; actual NSE sessions checked: 3,609;
  active-member range: 0..87; sessions not equal to 200: 3,609
- Known-at unresolved: 0; conflicts: 979 (`HIGH=626`, `CRITICAL=353`)
- Validation: `BLOCKED`; default importer dry-run: refused as designed;
  database touched: false
- The pre-rebuild package is preserved at
  `artifacts/nifty200_pit_v1_baseline_20260918_pre_rebuild`.

## Software remediation verification

The following defects were repaired and regression-tested in the current
worktree: provider fallback now continues only for availability categories;
AI risk inputs require verified/canonical-promoted, hash-bound, available
market data; backup locking spans copy and verification; destructive database
cleanup requires an explicit disposable target; dashboard non-finite profit
factor and monthly-return calculations are safe; PIT identity sentinels and
cross-instrument alias overlaps fail closed; and active foundation approval
certificates require `PASS` plus code-SHA binding.

- Full suite: `936 passed, 3 warnings`
- PIT-focused suite: `44 passed`
- Storage-focused suite: `9 passed`
- Ruff: pass
- Mypy (`ai_research tools data_platform storage`): pass, 57 files
- Pyright: 0 errors, 867 warnings
- Compileall: pass
- Dashboard UI build: pass
- Gitleaks: not installed in this environment

The build contacted only free public sources already present in the local
corpus plus refreshed official NSE files. The added official files were
`EQUITY_L.csv`, `symbolchange.csv`, and `namechange.csv`; the latter two add
manual-review candidates only because they do not provide historical ISIN
continuity.

## Requirement matrix

| Area | Measured result | Status | Remaining dependency |
|---|---:|---|---|
| Stable raw observation IDs | 1,866/1,866 populated | FIXED | None in software; rebuild provenance must be retained |
| Dirty-worktree code identity | `UNCOMMITTED:<hash>` in manifest | FIXED | Commit the exact reviewed code before certification |
| Paper execution stage binding | Requires `PAPER_ACTIVE` | FIXED | Human approval and foundation certification still required |
| Cancellation terminal state | Late worker cannot overwrite `CANCELLED` | FIXED | None in software |
| PIT alias provenance | Accepted aliases included in dataset hash | FIXED | Historical aliases remain unresolved unless certified |
| Alias period validation | Inverted/overlapping accepted periods rejected | FIXED | Manual review for any future candidates |
| Official identity-change evidence | 954 candidates retained | PARTIAL | Historical ISIN/security-master evidence required before certification |
| Source hash integrity | 362 sources, 0 hash failures | PASS | None for current bytes |
| Historical durable identity | 43.2906% certified; 3,364 unresolved | BLOCKED | Period-valid first-party identity evidence |
| Initial anchor | `NOT_ESTABLISHED` | BLOCKED | Official 2012-01-02 membership or causally complete backward chain |
| Monthly checkpoint coverage | 58 valid; 118 missing/non-200 | BLOCKED | Official checkpoint or documented methodology decision |
| Replay counts | 0..87; 3,609/3,609 sessions not 200 | BLOCKED | Anchor and certified event/identity chain |
| Official event conflicts | 979 total; 353 CRITICAL, 626 HIGH | BLOCKED | Resolve duplicate/collision/absent-member assertions with first-party evidence |
| Import safety | Dry run refused by blocked manifest; database untouched | PASS | No import until validation PASS and explicit approval |

## Exact remaining blocker groups

The complete row-level list is [blocker_ledger.csv](../artifacts/nifty200_pit_v1/blocker_ledger.csv).

- `MISSING_DURABLE_IDENTITY`: 625 rows, 70 dates, 84 symbols/company labels;
  source assertions span 2012-04-27 through 2026-06-30, with one pre-campaign
  2011-12-14 observation retained because it affects the initial chain.
- `MISSING_INITIAL_ANCHOR`: 292 rows, 44 dates, from 2012-09-28 through
  2026-06-30. These are not evidence that a synthetic initial set may be used.
- `DUPLICATE_EVENT`: 55 rows, from 2015-09-28 through 2026-06-30.
- `OTHER`: 6 rows, including same-day event collisions retained in the
  conflict report.
- `COUNT_NOT_200`: 3,609 daily session rows. This is the dependent replay
  failure produced by the missing initial anchor and unresolved event chain;
  it is not 3,609 independent source failures.
- Monthly coverage: 68 months have no acquired official checkpoint and 50
  official checkpoints contain 201 unique rows rather than the required 200.
  The 50 non-200 checkpoints are April 2016 through May 2020.

The monthly detail is [monthly_gap_analysis.csv](../artifacts/nifty200_pit_v1/monthly_gap_analysis.csv).
The identity and security/date/source fields for every blocker are in the
ledger; no fuzzy match or successor inference was promoted.

The complete current blocker ledger remains unchanged after the software
remediation rebuild. `COUNT_NOT_200` is a dependent replay failure, not 3,609
independent source gaps. The independent evidence gaps are 625 durable-identity
rows, 292 initial-anchor rows, 68 missing monthly checkpoints, 50 non-200
checkpoints, 55 duplicate-event rows, and 6 other collision rows.

## Correct next closure sequence

1. Obtain free first-party historical NSE security-master/ISIN evidence for the
   ledger's 84 unresolved symbols/company labels. Treat symbol/name-change
   tables as candidates until an ISIN/security continuity record is available.
2. Obtain or certify the exact NIFTY/CNX-200 membership on 2012-01-02, or a
   fully first-party backward chain that proves it. Do not reverse-replay a
   later checkpoint as an anchor.
3. For every unresolved event, bind announcement/publication time, effective
   date, durable identity, and source hash; reconcile duplicate and same-day
   collisions one event at a time.
4. Decide through documented methodology governance whether monthly checkpoints
   are required. If retained, obtain the 68 missing months and explain the 50
   201-row checkpoints without deleting valid rows.
5. Rebuild, validate on the real NSE calendar, inspect the ledger delta, and
   run the dry-run importer. Only a genuine `PASS` may proceed to a separately
   authorized QA/import decision.

## Safety state

`CAMPAIGN_STAGE_A=BLOCKED`, `INDEPENDENT_QA=NOT_ASSERTED`, and
`approved_for_import=false`. No external evidence was fabricated, and the
current blocked result must remain the authoritative outcome until the listed
evidence gaps are closed.
