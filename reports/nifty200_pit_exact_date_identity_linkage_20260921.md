# NIFTY-200 PIT exact-date identity linkage closure

Date: 2026-09-21  
Repository: `shashank297/algo-trading`  
Worktree: `C:\Python projects\algo trading-authoritative-evidence`  
Branch: `codex/nifty200-pit-authoritative-evidence`  
Working HEAD before this change: `08881a49ace9c965a4467eebed9d3e2e874e47c9`

## Change

The resolver now performs a conservative second pass for official A1/A2
observations. A company-only observation is linked only when exactly one
certified A1/A2 observation has the same effective date, action, and exact
normalized company name, and that identity-bearing observation has an explicit
symbol plus a certified period-valid ISIN resolution. B1 observations,
fuzzy matches, current-only evidence, ambiguous matches, and date/action
changes remain unresolved.

The raw assertions are retained. The rule does not fabricate an ISIN or
promote the date-only workbook assertion to an event; it permits the existing
redundant-workbook suppression to rely on the independently evidenced official
event.

## Measured before/after

| Measure | Before | After |
| --- | ---: | ---: |
| Source records | 597 | 597 |
| Source hash failures | 0 | 0 |
| Event observations | 1,544 | 1,544 |
| Canonical events | 671 | 671 |
| Constituent intervals | 325 | 325 |
| Total blocker rows | 222 | 208 |
| Missing durable-identity blockers | 15 | 1 |
| Monthly checkpoint blockers | 68 | 68 |
| Initial-anchor/replay blockers | 135 | 135 |
| Duplicate-event conflicts | 2 | 2 |
| Source-download blockers | 1 | 1 |
| Calendar certification blockers | 1 | 1 |
| Validation | `BLOCKED` | `BLOCKED` |

The 14 closed ledger rows are the company-only IndexInclExcl assertions that
have a unique same-date/same-action official identity-bearing observation. The
remaining identity row is `IBULHSGFIN` on 2013-11-15; the available explicit
ISIN observation is dated 2013-11-18 and is not backdated.

## Remaining actionable evidence dispositions

- `ABBOTINDIA`, 2022-03-31: official ADD exists, but no admissible prior DROP
  after the 2020 ADD was found. Keep the conflict as manual review; do not
  delete the ADD.
- `OFSS`, 2024-03-28: official ADD exists, but no admissible prior DROP after
  the 2022 ADD was found. Keep the conflict as manual review; do not delete
  the ADD.
- May 2012: the official download remains HTML rather than a valid ZIP; no
  verified official or Wayback archive was found.
- Calendar: the repository calendar and eight evidenced exceptions remain
  `PARTIAL_NOT_CERTIFIED`; no complete free historical NSE session corpus was
  admitted.
- Anchor/checkpoints: the direct 2012-01-02 roster remains unfound; backward
  replay remains diagnostic and `NOT_ESTABLISHED`.

## Safety

No B1 row was promoted. No fuzzy identity, current-only backdating,
predecessor/successor merge, synthetic membership, or validation weakening was
performed. Production `market_data.duckdb` and its WAL were not touched. The
importer remains dry-run only and must refuse while validation is blocked.

