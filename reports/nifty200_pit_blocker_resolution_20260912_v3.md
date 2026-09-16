# NIFTY-200 PIT empirical blocker-resolution iteration v3

This is an intermediate result, not completion or independent QA. It supersedes the current-status claims in `nifty200_pit_post_pr25_final_20260912.md`; that older report remains preserved as historical evidence.

## Verified state

- Branch: `codex/nifty200-pit-2012-anchor`.
- HEAD: `ea0f8bf9eb031abf3df9a7d46c568f72c0d5df31` plus uncommitted PIT changes.
- Fetched and live-verified origin/main: `a8f383149187b8d0bbfb23253ba81c464ec8563f`.
- GitHub PR #26 is MERGED (2026-09-11T11:35:52Z), all 13 reported checks SUCCESS. The earlier screenshot is not current CI state.
- Build timestamp: `2026-09-12T17:59:19.126404+00:00`.
- Scope: actual historical CNX/NIFTY 200; 2012-01-02 through 2026-08-20. No Stage A, strategy research/backtest, broker API, paper/live trading, or production database operation.
- Original repository governance changes remain untouched. No commit, push, or merge was performed in this iteration.

## Measured builds

| Metric | Before dated daily identities | Initial daily-identity build | Corrected v3 |
| --- | ---: | ---: | ---: |
| Sources | 367 | 371 | 373 |
| Hash errors | 0 | 0 | 0 |
| Observations | 1482 | 1482 | 1484 |
| Canonical events | 638 | 640 | 630 |
| Intervals | 298 | 299 | 300 |
| Conflicts | 172 | 176 | 167 |
| Monthly evidence gaps | 68 | 68 | 68 |
| Ledger entries | 3849 | 3853 | 3844 |
| Automated validation | BLOCKED | BLOCKED | BLOCKED |

The 371-source package was preserved verbatim under `artifacts/iteration_dated_bhavcopy_20260912/`. Older baseline and iteration packages remain intact.

## Corrected v3 package

- Sources: A1=369, A2=3, B1=1; zero source-hash errors.
- Canonical events: 314 ADD, 316 DROP; 16 withdrawn-schedule observations retained as SUPERSEDED, with `official_schedule_dispositions.csv` linking each to the exact official notice/hash.
- Historical snapshots: 21,650 rows across 108 dates; 58 literal 200-security checkpoints and 50 documented 201-security DVR checkpoints. All 108 satisfy the applicable count rule; 68 months still lack checkpoints.
- Current security master: 2,568 rows. Historical identity output: 7,588 rows, 3,451 unique instruments.
- Event identity resolution: 97.0803%, measured over 1,096 non-superseded first-party event observations; 32 unresolved observation identities. This replaces the misleading alias-table-only 100% metric. It is not a unique-security or full snapshot-date coverage percentage.
- Intervals: 300. Under the currently installed calendar, 3,609 sessions checked, minimum active count 0, maximum 133, all 3,609 below the expected count. The calendar audit found errors: do not interpret 3,609 as the certified actual-session total.
- Canonical known_at unresolved: 0. This does not certify calendar correctness or causality of rejected/noncanonical observations.
- Conflicts: 21 HIGH, 146 CRITICAL, total 167.
- Constituent interval SHA-256: `5b557f94b6b07fd1fae521099822514291449b52adbea78150396ec22a9eae55`.
- All artifact hashes listed by the manifest were independently recomputed by this agent and matched. This is an automated integrity check, not independent QA.
- Import dry-run: exit 1, `REFUSED_AS_DESIGNED`, because manifest validation is not PASS. Database not touched.
- Independent QA: `NOT_ASSERTED`; approved_for_import: `false`; Campaign Stage A: BLOCKED.

## Root causes fixed in this iteration

1. Historical identity acquisition: added date-scoped ISIN extraction from four official NSE daily bhavcopies. No OHLC data is used to infer membership or imported into a database. Evidence validity is restricted to the source's session, not extrapolated over split dates.
2. Daily-file instrument-type contamination: IFCI, MUTHOOTFIN and HUDCO also have bond-series rows under the same symbol. Restricting this parser to EQ prevents those debt ISINs from producing false equity ambiguities.
3. March 18, 2015 multi-date release: section A applies March 24 to other indices; section B explicitly applies March 27 to CMC/COX&KINGS in CNX 200. Scoped date parsing recovers both announcements. No missing-announcement ledger entries remain in v3.
4. Withdrawn schedules: applied content-hash-bound dispositions for the November 2013 holiday change, the September 2017 Reliance Capital reschedule, and the March 2020 COVID postponement. Old assertions are retained; no replacement date/event is invented.
5. Incremental official harvesting previously replaced the existing catalogue. It now preserves existing rows and deduplicates identical URL/hash acquisitions, with regression coverage.
6. Reporting: daily coverage now uses the validator's documented historical expected count. Identity percentages use required observations, not only successful aliases. Automated PASS cannot grant campaign readiness or import approval.

## Remaining ledger: not a list of independent root causes

| Type | Rows | Interpretation / next action |
| --- | ---: | --- |
| COUNT_NOT_200 | 3609 | Per-session symptoms of incomplete reconstruction, not 3,609 unrelated missing documents; calendar itself also needs correction. |
| MONTHLY_SNAPSHOT_MISSING | 69 | 68 individual months plus one aggregate coverage-conflict row. |
| MISSING_INITIAL_ANCHOR | 140 | Removal-of-absent-member conflicts currently grouped here. Audit identity changes and missed historical additions before claiming all are caused by the initial anchor. |
| MISSING_DURABLE_IDENTITY | 4 | Workbook-only company-label linkage gaps listed below. |
| MISSING_OFFICIAL_EVENT | 16 | B1 assertions; 14 now refer to officially withdrawn schedules and should be classified as contradicted, not searched as missing historical facts. Remaining two have an official date discrepancy. |
| DUPLICATE_EVENT | 6 | Trace first-party removal/identity-change evidence for the exact cases below. |

Four unresolved workbook linkage cases: Great Eastern Shipping Co. Ltd. (2013-04-01); Orissa Min Dev Co Ltd. (2014-03-28); National Buildings Construction Corporation Ltd. (2016-04-01); Indian Railway Catering And Tourism Corporation Ltd. (2020-06-26). Several have matching first-party PDF symbol assertions; exact provenance-based company/identity linkage is still required. Do not auto-certify fuzzy names.

The 16 B1 discrepancies comprise CAIRN/CROMPTON on 2016-10-24 (official notice indicates 2016-11-15), RELCAPITAL/MFSL on 2017-09-29 (official reschedule to September 5), and 12 assertions on 2020-03-27 covered by the official deferral. Keep B1 provisional and retain the contradictory assertions in a disposition audit; do not promote them into canonical events.

Six duplicate-add conflicts: PIIND 2016-09-30; ABBOTINDIA 2022-03-31; ADANIPOWER 2023-03-31; OFSS 2024-03-28; FORTIS 2025-09-30; LAURUSLABS 2026-03-30. Some may reflect ISIN continuity rather than duplicate source events; no predecessor/successor equivalence has been assumed.

The current diagnostic reverse replay uses symbols and does not consistently apply official symbol changes. Its statement blaming the first divergence exclusively on the unproven anchor is not established. Correct the diagnostic before using it to decide external evidence is irreducible.

## Sources contacted in this iteration

- Official NSE daily identity file: `https://archives.nseindia.com/content/historical/EQUITIES/2020/MAR/cm27MAR2020bhav.csv.zip`, SHA-256 `f68e1c9c7b4d935282508238eca0c9b171691994640acdec2505513998d86385`.
- Other three daily files were acquired in the preceding continuation and consumed here: 2016-04-01, 2020-06-26, 2021-03-31.
- Official notices successfully downloaded from `https://www.niftyindices.com/Press_Release/ind_prs23032020.pdf` (SHA `55a9cd5f11b9036e274b397c1f43f607c632ccb31837339b7ac661de6037ea59`) and `ind_prs25032020.pdf` (SHA `4dd3a6df4bf53b0191cfcdb8575170d2685d742f4bd1055c09643eef5d802703`). Initial requests with the default requests user agent timed out on both www and apex hosts; a standard browser user agent succeeded. Subsequent console Unicode errors affected text display, not download or hashes.
- GitHub read-only PR #26 status and git fetch/ls-remote.
- NSE calendar circulars were separately acquired into a staging catalogue while the main builder ran. They are not included in the 373-source package. See `nifty200_pit_calendar_findings_20260912.md` for successful URLs/hashes and failed paths.
- Web search and official archive pages were used as discovery evidence. The research-ops skill kept discovery separate from locally hash-bound certification evidence.

## Separate Campaign governance findings

Live-fetched main still returns from `_ensure_campaign_1_family` after checking only maximum_trials/universe. `run_pipeline.py` still pins `8330bb013ffd1d22acb2c60d715066a43b239cd35b382e772c4a7d47c7d72a3c`. `docs/research_campaign_1_baseline_v2.md` is absent from origin/main but exists uncommitted in the original checkout. No silent governance fix was mixed into this PIT iteration.

## Artifacts and next action

All measured data are under `artifacts/nifty200_pit_v1/`, particularly `blocker_ledger.csv`, `unresolved_gaps.csv`, `validation_report.json`, `evidence_manifest.json`, `constituent_intervals.parquet`, and `official_schedule_dispositions.csv`. Machine-readable measurement: `reports/nifty200_pit_iteration_measured_20260912_v3.json`.

Next: classify the 16 B1 contradictions using the already acquired official evidence; finish date-valid identity and symbol-change replay audits; apply evidence-backed calendar overrides using the repository calendar; rebuild and compare again. Neither PASS nor an irreducible-external-gaps-only endpoint has been established.

Verification details are recorded separately in `nifty200_pit_blocker_verification_20260912_v3.json` and its command logs. At report creation, PIT=81 passed, storage=9 passed, Ruff passed, Mypy passed (57 files), Pyright=0 errors/783 warnings, compileall passed, git diff --check passed; full pytest was still running. Do not treat the preceding 929-test result as verification of this iteration.

Completion verified 2026-09-15 from the v3 command log: full pytest finished with **940 passed, 3 warnings in 596.23 seconds**, exit 0. This is the historical v3 result, not verification of later v4 edits.
