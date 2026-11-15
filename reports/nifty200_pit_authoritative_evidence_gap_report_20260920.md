# NIFTY-200 PIT authoritative-evidence phase report

## Scope and result

- Worktree: `C:\Python projects\algo trading-authoritative-evidence`
- Branch: `codex/nifty200-pit-authoritative-evidence`
- HEAD: `635acfcf62596c0c145f4032dde1e7020407e98e`
- `origin/main`: `635acfcf62596c0c145f4032dde1e7020407e98e`
- Campaign: `2012-01-02` through `2026-08-20`
- Build timestamp: `2026-09-20T12:28:00.568418+00:00`
- Initial as-is validation: `BLOCKED`
- Final validation: `BLOCKED`

The existing pipeline was used. No Campaign Stage A, research, backtest, paper/live trading, broker API, production database import, or WAL operation was performed. The previous generated baseline was preserved at `artifacts/nifty200_pit_v1_baseline_authoritative_phase_20260920`.

## Measured final build

| Metric | Result |
|---|---:|
| Total sources | 362 |
| A1 sources | 361 |
| A2 sources | 0 |
| B1 sources | 1 |
| Source hash failures | 0 |
| Event observations | 1,534 |
| Canonical events | 0 |
| Canonical ADD events | 0 |
| Canonical DROP events | 0 |
| Snapshot rows | 21,650 |
| Snapshot dates | 108 |
| Valid 200-member checkpoints | 58 |
| Missing/non-200 checkpoints | 68 |
| Current security-master rows | 2,578 |
| Historical identity rows | 6,896 |
| Unique historical instruments | 2,578 |
| Durable-ID resolution among historical event rows | 91.26%* |
| ISIN resolution among historical event rows | 91.26%* |
| Unresolved historical event identity cases | 1,520 |
| Constituent intervals | 0 |
| Campaign sessions checked | 3,609 |
| Minimum active constituents | 0** |
| Maximum active constituents | 0** |
| Sessions not at expected count | 3,609** |
| Unresolved `known_at` values | 0*** |
| Total conflicts | 1,145 |
| HIGH conflicts | 1,145 |
| CRITICAL conflicts | 0 |

\* This is an identity-enrichment ratio in the event-observation denominator, not certified historical interval coverage. Certified historical identity rows remain 0.

\*\* The replay is intentionally not considered evaluable because the initial anchor and canonical events are absent. These zeros must not be interpreted as a real market-membership count.

\*\*\* There are no canonical events on which to evaluate `known_at`; this is not evidence that the unresolved observations are causally complete.

The raw event actions were 758 ADD and 776 DROP observations, but none could be promoted to canonical events under the existing fail-closed identity and causal-evidence rules. Event review groups were A1 accepted 14, A1 superseded 3, A1 unresolved 681, A1 manual review 464, and B1 unresolved 372.

## Blocker inventory

The generated blocker ledger contains 1,215 rows:

- `MISSING_DURABLE_IDENTITY`: 1,143
- `MISSING_INITIAL_ANCHOR`: 1
- `MONTHLY_SNAPSHOT_MISSING`: 69
- `OTHER`: 2

The exact per-row evidence-gap inventory contains 1,590 rows at [nifty200_pit_authoritative_evidence_gap_report.csv](C:/Python%20projects/algo%20trading-authoritative-evidence/reports/nifty200_pit_authoritative_evidence_gap_report.csv):

- 1,520 unresolved event-observation rows;
- 1 missing 2012-01-02 initial-anchor row;
- 68 missing monthly-checkpoint rows;
- 1 calendar-certification row.

The 68 monthly gaps are classified as `A_NO_SNAPSHOT_EVIDENCE` in [nifty200_pit_monthly_gap_analysis.csv](C:/Python%20projects/algo%20trading-authoritative-evidence/reports/nifty200_pit_monthly_gap_analysis.csv):

- 2012-01 through 2013-03: 15 months;
- 2022-04 through 2026-08: 53 months.

The exact 30 residual identity cases remain listed in [nifty200_pit_residual_identity_cases.csv](C:/Python%20projects/algo%20trading-authoritative-evidence/reports/nifty200_pit_residual_identity_cases.csv). They affect dated rows for BAJAJHFL, BHARTIHEXA, ITCHOTELS, LICI, NTPCGREEN, SONACOMS, TATATECH, GROWW, GVT&D, ICICIAMC, LENSKART, LGEINDIA, TATACAP, TMCV, OLAELEC, 360ONE, ENRIN, DELHIVERY, JSWINFRA, POONAWALLA, HYUNDAI, PREMIERENE, SWIGGY, VMM, WAAREEENER, and PATANJALI. The broader unresolved set also contains historical company-only and symbol-only observations.

## Evidence searches and outcome

The following free sources were contacted or checked:

- [Official Nifty-200 page](https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-200) and its current constituent endpoint. It is current-only and did not establish the 2012-01-02 anchor.
- [Official Nifty monthly reports](https://www.niftyindices.com/reports/monthly-reports) and [official historical-data page](https://www.niftyindices.com/reports/historical-data). The historical UI and current report links did not yield hashable date-relevant files for the 68 missing months.
- [Official NSE equity-market data downloads](https://www.nseindia.com/static/products-services/equity-market-data-reports-download), [NSE historical reports](https://www.nseindia.com/static/resources/historical-reports-capital-market-daily-monthly-archives), and the [NSE master-data specification](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_MasterData_Technical_Specifications.pdf).
- Official current `EQUITY_L.csv`, `symbolchange.csv`, and `namechange.csv`. These were harvested and hashed, but the current master cannot be backdated and the change files do not independently prove a period-valid ISIN interval.
- Official Nifty press-release material and archived official URL/Wayback checks. No full, date-relevant 2012-01-02 roster was admitted.
- The B1 reconstruction dataset was acquired only as a search index. It remains provisional and unresolved; no B1 row was promoted by itself.

Examples of official filings found during search, such as the [Patanjali NSE filing](https://nsearchives.nseindia.com/corporate/PATANJALI_18062023192649_Letter_to_SEs_dated_18062023.pdf), can support a later identity chain only when the full dated predecessor/successor and validity interval are proven. They were not used to fabricate or auto-certify historical intervals in this phase.

## What would close the remaining blockers

1. A hashable official full NIFTY-200/CNX-200 constituent roster for 2012-01-02, or a formally admissible date-relevant chain that proves the complete anchor.
2. Hashable official constituent checkpoints for the 68 missing months, or an explicit governance decision approving a different checkpoint contract. The contract was not changed in this phase.
3. For each unresolved identity row, a period-valid official NSE security master, corporate-action notice, or dated filing linking the exact historical symbol/company to the exact ISIN and validity interval. Fuzzy matching, current-master backdating, name-only matching, and unconfirmed predecessor/successor merges remain prohibited.
4. A hashable authoritative NSE trading-calendar corpus with documented holidays, special sessions, and parser validation for the complete campaign period.
5. After those sources are available: rebuild, canonicalize only evidence-supported events, replay all actual sessions, reconcile every checkpoint, rerun validation, and only then reconsider the dry-run importer.

## Safety and verification

- Dry-run importer: `REFUSED_AS_DESIGNED`, exit code 1 because the manifest was not `PASS`; `database_touched=false`.
- Independent QA: `NOT_ASSERTED`.
- Import approval: `NOT GRANTED` / `approved_for_import` remains false.
- Production `market_data.duckdb` and `market_data.duckdb.wal` were not modified.

Focused and quality checks:

- NIFTY-200 PIT tests: `104 passed in 3.35s`.
- Storage tests: `9 passed in 13.75s`.
- Full suite: `1004 passed, 3 warnings in 509.90s (0:08:29)`.
- Ruff: `All checks passed!`.
- Mypy: `Success: no issues found in 58 source files`.
- Pyright: `0 errors, 874 warnings, 0 informations`.
- Compileall: exit code 0.
- `git diff --check`: clean.

## Artifact paths

- [blocker_ledger.csv](C:/Python%20projects/algo%20trading-authoritative-evidence/artifacts/nifty200_pit_v1/blocker_ledger.csv)
- [unresolved_gaps.csv](C:/Python%20projects/algo%20trading-authoritative-evidence/artifacts/nifty200_pit_v1/unresolved_gaps.csv)
- [validation_report.json](C:/Python%20projects/algo%20trading-authoritative-evidence/artifacts/nifty200_pit_v1/validation_report.json)
- [evidence_manifest.json](C:/Python%20projects/algo%20trading-authoritative-evidence/artifacts/nifty200_pit_v1/evidence_manifest.json)
- [constituent_intervals.parquet](C:/Python%20projects/algo%20trading-authoritative-evidence/artifacts/nifty200_pit_v1/constituent_intervals.parquet)
- `constituent_intervals.parquet` SHA-256: `3ea54397b11bb45e76ac3c3cf5caaa8821fa2f929a4e11dc22604034e6f138b7`
- [dry_run_import_result.json](C:/Python%20projects/algo%20trading-authoritative-evidence/artifacts/nifty200_pit_v1/dry_run_import_result.json)
- [authoritative phase baseline](C:/Python%20projects/algo%20trading-authoritative-evidence/reports/nifty200_pit_authoritative_phase_baseline_20260920.md)

## Working-tree handling

The pre-existing local modifications were preserved and not mixed into the PIT implementation:

- `reports/nifty200_pit_2012_anchor_forensics_20260911.md`
- `reports/nifty200_pit_initial_anchor_20120102.md`

This phase added the baseline report and the final evidence-gap reports. Generated build artifacts remain local and are not an import or approval action. No commit, push, or merge was performed.

## Final status

NIFTY-200 PIT RECONSTRUCTION:
DATA EVIDENCE BLOCKED

INDEPENDENT QA:
NOT ASSERTED

CAMPAIGN STAGE A:
BLOCKED

## 2026-09-21 follow-up evidence lead

The official NSE [July 19, 2013 listing notice](https://nsearchives.nseindia.com/content/press/19072013.htm)
was checked for the remaining `IBULHSGFIN` identity blocker. It explicitly
maps `IBULHSGFIN` / Indiabulls Housing Finance Limited to ISIN
`INE148I01020` and gives an admission date of July 23, 2013, which is before
the unresolved November 15, 2013 event. The evidence is not yet admitted to
the build because the exact official HTML bytes could not be acquired through
the repository harvester in this environment for local hashing. The blocker
therefore remains open pending a hashable local copy.

The official [NSE exchange-communication holiday page](https://www.nseindia.com/resources/exchange-communication-holidays),
[historical reports page](https://www.nseindia.com/static/resources/historical-reports-capital-market-daily-monthly-archives),
and the official [2012 annual report](https://nsearchives.nseindia.com/global/content/about_us/NSEIL_Annual_Report_2012.pdf)
and [2013 annual report](https://nsearchives.nseindia.com/global/content/about_us/NSEIL_Annual_Report_2013.pdf)
were also checked. They provide specific session evidence but not a complete
hashable 2012-2026 equity-session corpus, so calendar provenance remains
`PARTIAL_NOT_CERTIFIED`.

## 2026-09-21 calendar date-level audit

The rebuild now emits `reports/nifty200_pit_calendar_gap_analysis.csv` and
`artifacts/nifty200_pit_v1/calendar_gap_analysis.csv`. The 5,345 campaign-date
rows classify 5,337 dates as `PACKAGE_ONLY`, six dates as
`VERIFIED_EXCEPTION` (covering eight verified overrides), and January 7 and
March 3, 2012 as `UNRESOLVED_OFFICIAL_LEAD`. The two 2012 rows retain the
annual-report URL but no SHA because the exact official bytes were not
acquired locally. This is an evidence accounting improvement only; the
calendar gate remains fail-closed.
