# NIFTY-200 PIT empirical result: v10

Build: **2026-09-15T16:11:02.362588+00:00**. Automated validation remains **BLOCKED**. This is continued empirical closure work, not a completed or import-approved reconstruction.

## Repository and safeguards

Worktree: `C:\Users\Shukla\AppData\Local\Temp\nifty200-pit-security-master`.
Branch: `codex/nifty200-pit-2012-anchor`.
HEAD: `ea0f8bf9eb031abf3df9a7d46c568f72c0d5df31` plus uncommitted PIT changes.
Fetched origin/main: `a8f383149187b8d0bbfb23253ba81c464ec8563f`.

The original checkout's existing governance changes are preserved and excluded from this work. No commit, push, merge, production DB/WAL operation, authoritative import, Campaign Stage A, backtest/research configuration, broker API or trading operation was performed. Independent QA is NOT_ASSERTED and import approval is NOT_GRANTED.

## Latest measured package

| Measurement | Result |
| --- | ---: |
| Sources used | 385 |
| A1 / A2 / B1 | 381 / 3 / 1 |
| Source hash errors | 0 |
| Event observations | 1,580 |
| Canonical events | 725 |
| ADD / DROP | 362 / 363 |
| Monthly snapshot rows / dates | 21,650 / 108 |
| Literal 200-security checkpoints | 58 |
| Historical expected-count checkpoints, including DVR-era 201 | 108 |
| Missing monthly checkpoints | 68 |
| Current security-master rows | 2,568 |
| Historical identity rows | 7,912 |
| Unique historical instruments | 3,451 |
| Durable-ID / ISIN resolution | 97.3132% / 97.3132% |
| Unresolved first-party identity observations | 32 of 1,191 |
| Constituent intervals | 354 |
| Campaign sessions checked | 3,613 |
| Active constituent count minimum / maximum | 0 / 128 |
| Sessions failing historical expected count | 3,613 |
| Canonical known_at unresolved | 0 |
| Total / HIGH / CRITICAL conflicts | 129 / 1 / 128 |
| Duplicate-add conflicts | 0 |
| Blocker ledger rows | 3,810 |
| Initial / final validation for this continuation | BLOCKED / BLOCKED |

Identity percentages describe resolver output, not independent certification of validity periods. Zero canonical known_at failures does not certify excluded observations. Calendar audit remains PARTIAL_NOT_CERTIFIED: eight verified overrides supplement the existing NSE calendar, but the full holiday/special-session campaign audit is unfinished. Matching checkpoint counts do not establish replay set equality. No initial constituents were fabricated to improve counts.

## Closures and before/after

Since v6, conflicts fell **142 -> 138 -> 135 -> 134 -> 129**, through separate complete builds with frozen artifacts:

1. Hash-bound visual extraction of the official August 2021 scan recovered 12 genuine events and removed four conflicts.
2. Two dated official bhavcopies corrected PIIND and AJANTPHARM identities, removing three conflicts.
3. The March 2024 IREDA revocation/BSE inclusion was correctly processed from the official multi-index table, removing the last duplicate-add conflict. Original announcements and B1 observations remain preserved; no artificial DROP was generated.
4. Four further official bhavcopies corrected six ADD identities and removed five more conflicts. There was no code change between v9 and v10; this was a data-evidence iteration.

The six v10 corrected ADDs are AMARAJABAT (2013-04-01), KSCL (2014-09-19), BERGEPAINT and GRUH (2015-03-27), NAVINFLUOR and YESBANK (2020-09-25). Exact previous and replacement rows are retained in `nifty200_pit_replaced_events_20260915_v10.csv` and `nifty200_pit_recovered_events_20260915_v10.csv`.

New v10 first-party identity evidence actually retrieved, validated and consumed:

| Date | Official source | SHA-256 |
| --- | --- | --- |
| 2013-04-01 | [NSE bhavcopy](https://nsearchives.nseindia.com/content/historical/EQUITIES/2013/APR/cm01APR2013bhav.csv.zip) | ac3ed3621278660d58650f982a99b97dcab52fb0905fb7b99871fc44e05552a8 |
| 2014-09-19 | [NSE bhavcopy](https://nsearchives.nseindia.com/content/historical/EQUITIES/2014/SEP/cm19SEP2014bhav.csv.zip) | 60024fed82ae7a9436e7242b2dec1cca7292fd73fd5bef49d699b2f04fa9bd4d |
| 2015-03-27 | [NSE bhavcopy](https://nsearchives.nseindia.com/content/historical/EQUITIES/2015/MAR/cm27MAR2015bhav.csv.zip) | 5ec6a39cd8b5070d314f4a3a5dc198ef3b5d18c6cf18c0644c021f35b6fce096 |
| 2020-09-25 | [NSE bhavcopy](https://nsearchives.nseindia.com/content/historical/EQUITIES/2020/SEP/cm25SEP2020bhav.csv.zip) | 579148b2c647823c4b6681d55c93ac6042f0982e39fe067c3d7eb23a17eac2f9 |

These files establish dated normal-equity identity only. They do not establish index membership and were not imported as prices. Their mappings remain day-scoped; different ISINs were not merged by name or symbol similarity.

## Exactly what remains

The 129 conflicts comprise 128 absent-member removals and one aggregate monthly-coverage conflict. All 128 removal securities/dates are listed in `nifty200_pit_absent_member_root_cause_audit_20260915_v10.csv`, including original source hashes and prior canonical ADD lineage:

- **123** have no earlier canonical ADD. Whether they are initial members or have missing ADD evidence is not proven.
- **5** have earlier same-symbol ADDs under different ISINs: J&KBANK (DROP 2016-04-01), KARURVYSYA (2018-09-28), NBCC (2020-06-26), NATCOPHARM (2022-03-31), and BATAINDIA (2024-03-28). Official dated security/corporate-action evidence is needed to distinguish real ISIN transitions from incorrect identity periods and represent continuity correctly.

The current ledger's MISSING_INITIAL_ANCHOR label for all removals remains overbroad and must be refined. Its 3,810 rows also include 3,613 daily count consequences and 69 monthly entries (68 months plus the aggregate). They must not be reported as 3,810 independent missing documents.

All 68 missing monthly URLs were investigated. Results are in `nifty200_pit_monthly_gap_evidence_20260915.csv` and the source-inventory JSON:

- **15 months**, January 2012-March 2013: HTTP 200 responses are HTML titled Error 404, not ZIP files.
- **53 months**, April 2022-August 2026: valid official ZIPs contain other index reports but no NIFTY-200 table.

Those negative-evidence downloads are separately staged, not counted in the 385-source build. They establish failure of these particular URLs/archives, not that no free alternative exists. No other index was substituted.

Wayback CDX for the official `ind_cnx200list.csv` returned captures dated 2014-01-22, 2014-07-09 and 2015-03-25; none predates the target starting set. The checked `ind_nifty200list.csv` URL returned no captures. Exact results are in `nifty200_pit_anchor_cdx_probe_20260915.json`. The July 2011 launch notice gives methodology but no constituent list. The January 2012 initial set remains unproven.

Other unfinished requirements: period-valid identity review, full checkpoint set reconciliation (the current anchor diagnostic compares only 58 checkpoints and misses some renames), ledger completeness/classification, event-date snapshot materialization, remaining narrative event extraction, and complete calendar/known-at audit. These are not yet all shown to be irreducible external/manual gaps. The goal remains active.

## Artifacts and checksum

Current local package: `artifacts/nifty200_pit_v1/`. Frozen exact v10 package: `artifacts/iteration_identity_continuity_20260915_v10/`. Earlier v7-v9 packages and the original blocked baselines remain preserved.

Key paths under either package: `blocker_ledger.csv`, `unresolved_gaps.csv`, `validation_report.json`, `evidence_manifest.json`, `constituent_intervals.parquet`. Detailed measurements: `reports/nifty200_pit_iteration_measured_20260915_v10.json`.

SHA-256 of constituent_intervals.parquet:
`68dfda87a69294d4db03ad7fa61f08a0f484d84a6d6c08ed6214c3b727a34da5`.

All manifest-listed artifact hashes matched recomputation by this agent. This is not independent QA. The dry-run importer returned exit 1 / REFUSED_AS_DESIGNED: `Manifest validation is not PASS; import refused`. No database touched; approved_for_import remains false.

## Verification and separate governance

The unchanged v9/v10 code passed PIT 97 tests, storage 9 tests, and the full suite **956 passed, 3 warnings in 471.06s**. Ruff passed; Mypy passed on 57 files; Pyright zero errors / 783 warnings; compileall passed; git diff --check passed. Commands/logs are in `nifty200_pit_blocker_verification_20260915_v9.json`. v10 changed only evidence and generated reports, and the complete builder/validator/import dry-run was rerun on that evidence.

Code changed during the preceding extraction iterations: existing ocr.py, parse_pdf.py and build_public_dataset.py, the bundled source-hash transcription JSON, and focused parser/public-dataset/transcription tests. v10 added dated evidence and reports only. Across the ongoing task the tracked diff was 23 files, 1,872 insertions and 126 deletions, plus untracked tests/reports/evidence; full status and diff-stat are retained in `nifty200_pit_workspace_state_20260915_v9.json`. That snapshot predates this v10 report and acquisition reports. Original-checkout governance edits are unchanged.

Separate read-only main-branch governance verification confirms `_ensure_campaign_1_family` still returns after only maximum_trials/universe checks, run_pipeline.py still pins `8330bb013ffd1d22acb2c60d715066a43b239cd35b382e772c4a7d47c7d72a3c`, while risk_policy.yaml declares and recomputes to `9839425d1c770c2b25744b110122c7b44cd3d7e4ee0e94dbb942dfa07f9d2092`. The baseline_v2 document is absent from main. Evidence is in `nifty200_pit_separate_governance_check_20260915.json`. These were not silently repaired in PIT work.

Recommended commits after review: keep PIT extraction/evidence corrections with their regressions; separate shared calendar API fixes and governance work. Do not commit production data, secrets, logs, or raw/generated artifacts wholesale.

## Next action

Refine the existing blocker ledger using the demonstrated monthly failure categories and five remaining identity discontinuities. Obtain the relevant official security/split/ISIN-transition notices and continue initial-anchor/archived-checkpoint discovery, then rebuild and compare with frozen v10. Do not start Campaign Stage A or import while those requirements remain unproved.
