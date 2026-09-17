# NIFTY-200 PIT empirical closure iteration v4

Build: 2026-09-15T02:12:30.825358+00:00. Status: DATA EVIDENCE BLOCKED.
This is an intermediate measured result, not completion or independent QA.

## Repository and preservation

- Branch: `codex/nifty200-pit-2012-anchor`.
- HEAD: `ea0f8bf9eb031abf3df9a7d46c568f72c0d5df31` plus uncommitted PIT changes.
- Freshly fetched origin/main: `a8f383149187b8d0bbfb23253ba81c464ec8563f`.
- Original checkout governance edits in research.py, tests/test_campaign1_governance.py, the hardened baseline report, and untracked governance documents remain untouched.
- No commit, push, merge, Campaign execution, broker call, or production database operation was performed in this iteration.
- Exact pre-iteration evidence remains in `artifacts/iteration_notice_closure_20260912_v3`; the new package is also preserved in `artifacts/iteration_calendar_causality_20260915_v4`.

## Measured before and after

| Metric | v3 | v4 |
| --- | ---: | ---: |
| Sources | 373 | 377 |
| A1 / A2 / B1 sources | 369 / 3 / 1 | 373 / 3 / 1 |
| Source hash failures | 0 | 0 |
| Observations | 1484 | 1484 |
| Canonical events | 630 | 630 |
| ADD / DROP | 314 / 316 | 314 / 316 |
| Snapshot rows / dates | 21650 / 108 | 21650 / 108 |
| Valid historical expected-count checkpoints | 108 | 108 |
| Missing monthly checkpoints | 68 | 68 |
| Intervals | 300 | 300 |
| HIGH / CRITICAL conflicts | 21 / 146 | 7 / 146 |
| Total conflicts | 167 | 153 |
| Sessions checked | 3609 | 3611 |
| Active membership min / max | 0 / 133 | 0 / 133 |
| Sessions failing expected count | 3609 | 3611 |
| Ledger rows | 3844 | 3832 |
| Validation | BLOCKED | BLOCKED |

The changed session denominator is a calendar correction, not deterioration in membership data. Four official calendar documents were merged from the earlier staging catalogue, and six hash-bound overrides represent four dates (including interruptions). The calendar remains PARTIAL_NOT_CERTIFIED: all campaign years still need exceptional-session/holiday audit.

Sixteen B1 observations matched officially withdrawn schedules and were excluded from reconciliation, while retained unchanged in the evidence observations. This eliminated fourteen conflict groups, not sixteen independent missing events. No B1 row was promoted.

Twenty canonical knowledge times changed: CRISIL and ARVIND moved from 2015-01-26 to 2015-01-27; eighteen events announced 2016-08-12 moved from 2016-08-15 to 2016-08-16. The exact securities, source URLs, old and new timestamps are recorded in `nifty200_pit_iteration_measured_20260915_v4.json`. Exact source timestamps and same-day review cases were not rewritten. Zero unresolved canonical known_at values does not certify the entire calendar or all excluded observations.

Identity metrics remain: current master 2568 rows; historical identity table 7588 rows; 3451 unique historical instruments; 1096 non-superseded first-party event observations; 32 unresolved observations; durable-ID and ISIN resolution each 97.0803%. These are implementation measurements, not independent certification of historical identity periods.

## Remaining ledger and root-cause cautions

| Current ledger classification | Rows | Interpretation / next action |
| --- | ---: | --- |
| COUNT_NOT_200 | 3611 | Session-level consequences of incomplete intervals; not 3611 independent evidence gaps. Establish anchor and reconcile event/identity continuity. |
| MONTHLY_SNAPSHOT_MISSING | 69 | 68 exact monthly gaps plus one aggregate coverage conflict. Do not double count. |
| MISSING_INITIAL_ANCHOR | 140 | Current classifier labels absent-member removals this way. Identity transitions and missing events may also cause them; root causes are not all proven. |
| DUPLICATE_EVENT | 6 | Trace PIIND 2016-09-30, ABBOTINDIA 2022-03-31, ADANIPOWER 2023-03-31, OFSS 2024-03-28, FORTIS 2025-09-30, LAURUSLABS 2026-03-30. |
| MISSING_DURABLE_IDENTITY | 4 | Three name-linkage issues plus one confirmed truncated PDF company name; see below. |
| MISSING_OFFICIAL_EVENT | 2 | CAIRN DROP and CROMPTON ADD dated 2016-10-24 in B1. Local official release supports 2016-11-15 for NIFTY 200; implement evidence-bound contradiction disposition, not promotion. |

### Next verified extraction/linkage targets

The workbook `IndexInclExcl.xls` has SHA-256 `8869bb7c4df67403131a494a8cc65509e80828f9438bc150b506cdbf55378046`.

- Great Eastern Shipping Co. Ltd., DROP 2013-04-01: official release uses **The** Great Eastern Shipping Co. Ltd., GESHIP (`ind_prs13022013.pdf`, SHA-256 `747ada17f17537dd854ff497062e263dd32b84598eb74e36795e230c95afff69`).
- Orissa Min Dev Co Ltd., DROP 2014-03-28: release uses Orissa Min **Development** Co. Ltd., ORISSAMINE (`ind_prs27022014.pdf`, SHA-256 `ad374e90736c719b626d0d774b418edb350d2aff5fafb62c3734468a8e7db7c3`).
- National Buildings Construction Corporation Ltd., ADD 2016-04-01: release uses National Buildings Construction **Corp.** Ltd., NBCC (`ind_prs22022016_2.pdf`, SHA-256 `db2e4802e43b68fcbfbbf2cb03cb59c6d5f9ebf086ab6687d5a15daa45c2525f`).
- Indian Railway Catering And Tourism Corporation Ltd., ADD 2020-06-26: `ind_prs10062020.pdf` wraps the company name across lines; parser retained only **Corporation Ltd.** with IRCTC (`ea83ae30ff9e8d80892e143ebd8f16fedd04c974e77d673539bb663a9f9de49e`). Fix row reconstruction with a real-corpus regression before resolving workbook redundancy.

The October 17, 2016 official release (`ind_prs17102016.pdf`, SHA-256 `e3ad170876e6278ad7a1e99cc924ba610c3f8be4ef0dc85cd2c146e2152ca4ea`) explicitly assigns NIFTY 200 to group C, effective November 15. Its page 5 lists CAIRN/CROMPTON. October 24 applies to other named index groups. This is inspected first-party evidence; implementation closure is still pending.

No fuzzy identity certification or predecessor/successor merging is authorized by these findings. Name linkage must be narrow, evidence-bound and regression-tested.

## Verification and import safety

All manifest-listed artifact hashes matched on independent recomputation (not independent QA). Interval SHA-256: `8ded38f936fc3f982d76f3a4029009b22d3b2f0bd736217d838c036251b3b63a`.

Importer was rerun with explicit interval and manifest paths and `--dry-run`: exit 1, `Manifest validation is not PASS; import refused`. Code inspection confirms this refusal precedes database construction. Independent QA NOT_ASSERTED; approved_for_import false; Campaign Stage A BLOCKED.

Verification currently completed: PIT 85 passed; storage 9 passed; Ruff passed; Mypy passed (57 source files); Pyright 0 errors / 783 warnings; compileall passed; git diff --check passed (line-ending warnings). Full pytest is running under verification driver v4; do not substitute the older v3 result (940 passed) for its result. Exact command outputs are versioned in `nifty200_pit_blocker_verification_20260915_v4.json` and companion logs.

## Exact next action

Additional free evidence acquired after this build: NSE CMTR65729 (2025-02-01 Budget session, 09:15-15:30) and CMTR59124 (2023-11-12 Muhurat session, 18:15-19:15), both HTTP 200. Their exact hashes and staging path are in `nifty200_pit_calendar_findings_20260912.md`. They are not part of v4's 377 sources or session count. Broad web searches for a 2012 CNX 200 constituent anchor did not produce a dated first-party list in the returned results; this is not proof none exists.

A read-only probe also reproduced remaining calendar API inconsistencies: the closed January 22 date is absent from decision sessions but still has 375 expected intraday minutes; `is_session_open` reports true during the March 2 interruption. See `nifty200_pit_calendar_api_probe_20260915.json`. These are code defects, not irreducible missing evidence; they still require regression-backed fixes.

Complete the current full-test run; fix the evidenced wrapped-row parser defect and narrowly link the three official workbook/release name variants; add regressions; rebuild and compare this frozen v4 baseline. Continue identity-period, initial-anchor and checkpoint reconciliation work. Remaining problems have not been shown to be irreducible external gaps.
