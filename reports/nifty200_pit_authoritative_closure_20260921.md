# NIFTY-200 PIT authoritative-evidence closure report

Date: 2026-09-21  
Repository: `shashank297/algo-trading`  
Worktree: `C:\Python projects\algo trading-authoritative-evidence`  
Branch: `codex/nifty200-pit-authoritative-evidence`  
HEAD: `08881a49ace9c965a4467eebed9d3e2e874e47c9`  
Local `origin/main`: `635acfcf62596c0c145f4032dde1e7020407e98e`

## Outcome

The existing NIFTY-200 PIT pipeline was rebuilt after the conservative exact
date/action/company identity-linkage fix. Validation remains correctly
`BLOCKED`; no evidence was fabricated, no B1 row was promoted, and no
production database or WAL was touched.

## Latest measured build

The latest validation artifact was generated at
`2026-09-21T04:11:13.696798+00:00`.

| Metric | Result |
| --- | ---: |
| Total source records | 597 |
| A1 / A2 / B1 sources | 590 / 6 / 1 |
| Source hash failures | 0 |
| Event observations | 1,544 |
| Canonical events | 671 |
| Canonical ADD / DROP | 327 / 344 |
| Snapshot rows / dates | 21,650 / 108 |
| Valid 200-member checkpoints | 58 |
| Missing or non-200 checkpoints | 68 |
| Current security-master rows | 2,578 |
| Historical identity rows | 230,784 |
| Unique historical instruments | 4,933 |
| Durable-ID resolution | 45.7902% |
| ISIN resolution | 45.7902% |
| Unresolved identity cases | 1 |
| Constituent intervals | 325 |
| Campaign sessions checked | 3,613 |
| Minimum / maximum active constituents | 0 / 119 |
| Sessions not at expected count | 3,613 |
| Unresolved `known_at` values | 0 |
| Total conflicts | 137 |
| HIGH conflicts | 1 |
| CRITICAL conflicts | 136 |
| Validation | `BLOCKED` |

Source-tier counts are from the generated source catalogue. The 135
`MISSING_INITIAL_ANCHOR` ledger rows are one root anchor failure plus
downstream replay consequences, not 135 independent missing documents.

## Implemented closure

`tools/nifty200_pit/instrument_resolver.py` now performs a conservative second
pass for official A1/A2 company-only observations. It links a company-only row
only when one and only one certified identity-bearing A1/A2 observation has
the same effective date, action, and normalized company name. It requires an
explicit symbol and period-valid resolved ISIN. B1, fuzzy, current-only,
ambiguous, and date/action-mismatched rows remain unresolved.

Focused regression coverage was added in
`tests/test_nifty200_pit_identity.py` for both exact linkage and rejection of
B1/date/action mismatches.

Measured effect:

| Measure | Before | After |
| --- | ---: | ---: |
| Total blocker rows | 222 | 208 |
| Durable-identity blocker rows | 15 | 1 |
| Closed identity rows | 0 | 14 |
| Validation | `BLOCKED` | `BLOCKED` |

## Official duplicate-event audit

The official Nifty Indices releases were checked as evidence, not used as a
reason to overwrite the event ledger:

- [Nifty Indices press-release archive](https://niftyindices.com/press-release)
- [June 10, 2020 replacement release](https://niftyindices.com/Press_Release/ind_prs10062020.pdf): lists Abbott India in the NIFTY 200 inclusion section.
- [February 23, 2021 replacement release](https://niftyindices.com/Press_Release/ind_prs23022021.pdf): lists OFSS as a NIFTY 200 exclusion.
- [February 24, 2022 replacement release](https://niftyindices.com/Press_Release/ind_prs24022022_1.pdf): lists ABBOTINDIA and OFSS as NIFTY 200 inclusions.
- [February 28, 2024 replacement release](https://niftyindices.com/Press_Release/ind_prs28022024.pdf): again lists OFSS as a NIFTY 200 inclusion.

These documents establish official assertions but do not establish the
missing prior DROP needed to make the repeated ADD events causally consistent.
Therefore the two rows remain `DUPLICATE_EVENT` / manual review:

1. `ABBOTINDIA`, effective `2022-03-31`: no admissible DROP after the
   `2020-06-26` ADD was found.
2. `OFSS`, effective `2024-03-28`: no admissible DROP after the `2022-03-31`
   ADD was found.

The exact missing document for each case is an official NIFTY 200 DROP or a
dated official correction/replacement notice explaining why the later ADD is
not a duplicate. The existing official ADD rows must not be deleted.

## Additional first-party evidence checks on 2026-09-21

An official NSE press page was found for the remaining historical identity
case: [NSE listing notice dated July 19, 2013](https://nsearchives.nseindia.com/content/press/19072013.htm).
It explicitly maps `IBULHSGFIN` / `Indiabulls Housing Finance Limited` to
`INE148I01020` and states that the equity shares were admitted to dealings
from July 23, 2013. This is temporally before the unresolved NIFTY-200 event
dated November 15, 2013 and is a strong closure candidate.

It was not promoted in this build because the repository harvester could not
acquire the official HTML bytes outside the browser evidence view: direct
HTTPS acquisition was blocked/timed out in the execution environment. No
local source file or SHA-256 was therefore created, and the blocker remains
open until the exact first-party bytes are acquired and added to the source
catalogue. This preserves the download-and-hash requirement rather than
certifying from search-result text.

For calendar provenance, the official [NSE exchange-communication holiday
page](https://www.nseindia.com/resources/exchange-communication-holidays),
[NSE historical reports page](https://www.nseindia.com/static/resources/historical-reports-capital-market-daily-monthly-archives),
and official annual-report evidence for 2012 special sessions were checked.
The [NSE 2012 annual report](https://nsearchives.nseindia.com/global/content/about_us/NSEIL_Annual_Report_2012.pdf)
and [NSE 2013 annual report](https://nsearchives.nseindia.com/global/content/about_us/NSEIL_Annual_Report_2013.pdf)
document specific special sessions, but they do not by themselves provide a
complete, hashable 2012-2026 equity-session calendar. The calendar blocker
therefore remains `PARTIAL_NOT_CERTIFIED`.

The 2012 annual report specifically records special trading sessions on
January 7, 2012 and March 3, 2012. Those dates are material to the campaign
range, but the report is not a substitute for a complete period-by-period
holiday and session corpus.

The build now emits a date-level calendar evidence audit at
`reports/nifty200_pit_calendar_gap_analysis.csv` and
`artifacts/nifty200_pit_v1/calendar_gap_analysis.csv`. It contains all 5,345
calendar dates from 2012-01-02 through 2026-08-20:

- 5,337 dates are `PACKAGE_ONLY` and require a complete hashable official
  session/holiday corpus for closure.
- 6 dates have `VERIFIED_EXCEPTION` evidence in the local corpus; these cover
  8 verified overrides because March 2, 2024 and May 18, 2024 each have both a
  special-session and interruption rule.
- January 7, 2012 and March 3, 2012 are explicit
  `UNRESOLVED_OFFICIAL_LEAD` rows from the 2012 annual-report investigation;
  the exact report bytes are not locally acquired and therefore have no SHA.

This artifact is diagnostic evidence accounting only. It does not make the
calendar certified and does not change the fail-closed validator.

## Remaining blockers

The generated `artifacts/nifty200_pit_v1/blocker_ledger.csv` contains:

| Blocker type | Rows | Required evidence or action |
| --- | ---: | --- |
| `MISSING_INITIAL_ANCHOR` | 135 | Hashable full NIFTY-200/CNX-200 roster for 2012-01-02, or an admissible complete date-relevant chain. |
| `MONTHLY_SNAPSHOT_MISSING` | 68 | Hashable authoritative checkpoints for the listed months, or an approved change to the checkpoint contract. |
| `MISSING_DURABLE_IDENTITY` | 1 | Period-valid official identity evidence for `IBULHSGFIN` on 2013-11-15; the available explicit identity evidence is dated 2013-11-18 and cannot be backdated. |
| `DUPLICATE_EVENT` | 2 | Official prior DROP or correction for ABBOTINDIA/OFSS, with the exact effective date. |
| `SOURCE_DOWNLOAD_FAILURE` | 1 | Valid official archive bytes for the May 2012 source URL; the cached response is HTML, not the expected ZIP. |
| `OTHER` | 1 | Complete authoritative NSE session/holiday corpus for 2012-01-02 through 2026-08-20, including exceptions. |

The anchor, monthly, calendar, and May-2012 issues are evidence gaps rather
than parser failures. The direct 2012 anchor remains `NOT_ESTABLISHED`, and
calendar provenance remains `PARTIAL_NOT_CERTIFIED`.

## Artifact references

- `artifacts/nifty200_pit_v1/blocker_ledger.csv`
- `artifacts/nifty200_pit_v1/unresolved_gaps.csv`
- `artifacts/nifty200_pit_v1/validation_report.json`
- `artifacts/nifty200_pit_v1/evidence_manifest.json`
- `artifacts/nifty200_pit_v1/constituent_intervals.parquet`
- `artifacts/nifty200_pit_v1/calendar_gap_analysis.csv`
- `artifacts/nifty200_pit_v1/historical_instrument_master.parquet`
- `reports/nifty200_pit_monthly_gap_analysis.csv`
- `reports/nifty200_pit_calendar_gap_analysis.csv`

SHA-256 of `constituent_intervals.parquet`:

`f5788d5a97393728dba3bd3603d435852273abcf66989cfd63addde9a4e1f14c`

Dry-run import result: `REFUSED_AS_DESIGNED`, exit code 1,
`database_touched=false`, because the manifest validation is not PASS.

## Verification

- NIFTY-200 PIT tests: `115 passed`
- Storage tests: `9 passed`
- Full suite: `1015 passed, 3 warnings`
- Ruff: passed
- Mypy: passed, 59 source files
- Pyright: passed, 0 errors, 875 warnings
- Compileall: passed
- `git diff --check`: passed

The calendar-gap regression test verifies that package-only dates,
unresolved official leads, and hash-verified exceptions remain distinct.

Independent QA remains `NOT_ASSERTED`. `approved_for_import` remains false.

## Final status

NIFTY-200 PIT RECONSTRUCTION:
DATA EVIDENCE BLOCKED

INDEPENDENT QA:
NOT ASSERTED

CAMPAIGN STAGE A:
BLOCKED
