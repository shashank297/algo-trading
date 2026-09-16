# NIFTY-200 PIT empirical closure: scanned notice iteration v7

Build timestamp: 2026-09-15T10:24:17.890437+00:00. DATA EVIDENCE BLOCKED.
This is an intermediate measured result, not completion, independent QA, or import approval.

## Repository and preservation

Branch `codex/nifty200-pit-2012-anchor`; HEAD `ea0f8bf9eb031abf3df9a7d46c568f72c0d5df31` plus uncommitted PIT changes. Freshly fetched origin/main is `a8f383149187b8d0bbfb23253ba81c464ec8563f`. No commit, push or merge in this iteration.

The original checkout's research.py, tests/test_campaign1_governance.py, hardened baseline report, untracked baseline_v2 and post-merge governance reports remain untouched. PIT work remains in the separate temporary worktree. No production database, WAL, Campaign Stage A, strategy research, broker, paper-trading or live-trading operation was performed.

Exact packages are frozen separately in `artifacts/iteration_parser_linkage_20260915_v5`, `artifacts/iteration_lettered_tables_20260915_v6`, and `artifacts/iteration_scanned_notice_20260915_v7`. Earlier blocked baselines remain intact.

## Measured progression

| Metric | v5 | v6 | v7 |
| --- | ---: | ---: | ---: |
| Sources | 379 | 379 | 379 |
| A1 / A2 / B1 | 375 / 3 / 1 | 375 / 3 / 1 | 375 / 3 / 1 |
| Source hash failures | 0 | 0 | 0 |
| Event observations | 1484 | 1567 | 1579 |
| Canonical events | 630 | 713 | 725 |
| ADD / DROP | 314 / 316 | 356 / 357 | 362 / 363 |
| Constituent intervals | 300 | 345 | 352 |
| Total conflicts | 147 | 142 | 138 |
| HIGH / CRITICAL | 1 / 146 | 1 / 141 | 1 / 137 |
| Duplicate ADD conflicts | 6 | 3 | 2 |
| Ledger rows | 3828 | 3823 | 3819 |
| Automated validation | BLOCKED | BLOCKED | BLOCKED |

All three builds contain 21,650 monthly snapshot rows on 108 dates. There are 58 literal 200-security checkpoints and 50 evidenced 201-security DVR-era checkpoints, for 108 matching the implemented historical count rule. There are 68 missing monthly checkpoints.

v7 checked 3,613 decision sessions from the existing NSE calendar implementation with eight hash-bound overrides. Calendar audit remains PARTIAL_NOT_CERTIFIED: this does not prove the campaign session list is exhaustive. Active constituent count is 0 to 133, and all 3,613 sessions fail expected count. No artificial initial 200-member set was inserted.

Identity measurements: current master 2,568 rows; historical identity table 7,588 rows; 3,451 unique historical instruments. Of 1,191 non-superseded first-party event observations, 32 lack resolved identities. Durable-ID and ISIN resolution are each 97.3132%. These are implementation metrics, not certification that all historical validity periods are correct. Canonical known_at unresolved count is zero; this does not cover excluded observations or certify the full calendar.

## Defects closed and exact evidence

The v6 lettered-section heading fix recovered 83 canonical events from official releases dated August 20, 2020 (16), August 17, 2023 (15), August 23, 2024 (30), and February 21, 2025 (22). The exact recovered rows and provenance are in `nifty200_pit_recovered_events_20260915_v6.csv`. Adjacent index sections remain excluded by bounded parsing.

The [August 23, 2021 official notice](https://www.niftyindices.com/Press_Release/ind_prs23082021.pdf) has no native text. Visual inspection of the original rendered page 1 confirms announcement August 23 and effective September 30, 2021 (close of September 29). Page 14 contains the NIFTY 200 table. SHA-256: `c9b9feef248ca89f7d8c8f12009e3d5c409eb4d6c793eee061fb93bf0af1231e`.

Recovered removals: ABBOTINDIA, BBTC, CESC, GODREJAGRO, IBULHSGFIN, VGUARD.
Recovered additions: ASTRAL, HINDCOPPER, INDIANB, IRFC, NATIONALUM, TATACOMM.

The transcription is explicitly labelled Codex visual extraction, NOT independent QA. It contains no inferred ISINs. Loading requires matching local PDF bytes, parent hash and first-party tier. The existing parser and resolver process the rows; raw lineage preserves the date page, event page and derivative SHA. `pdf_transcriptions.json` is included in the artifact manifest. Unknown scans cannot borrow these events. All 12 new canonical rows are in `nifty200_pit_recovered_events_20260915_v7.csv`; no prior canonical events were removed in v7.

## Remaining blockers and limits

The ledger contains 3,613 daily count failures, 69 monthly-coverage entries (68 months plus one aggregate), 135 absent-member-removal entries currently labelled MISSING_INITIAL_ANCHOR, and two duplicate-event conflicts. These are not 3,819 independent evidence gaps.

The initial January 2012 set remains unproven. Absent-member removals may also be caused by missing events or identity-period errors: the existing initial-anchor label is overbroad. The anchor diagnostic still ignores some identity/symbol transitions and does not reconcile all 108 expected-count checkpoints. Remaining scanned notices and narrative event notices need inspection. Historical identity periods, monthly gap evidence, calendar completeness and known-at review remain open. The remaining gaps have NOT been demonstrated irreducible.

PIIND is the next evidenced identity correction. Separately staged official bhavcopies for September 28, 2015 and September 30, 2016 both identify normal-equity PIIND as INE603J01030; the reconstruction assigns the corresponding additions INE603J01022. The September 2015 archive endpoint returned 403, but the alternative official nsearchives host supplied the file. Acquisition results preserve URLs, errors, hashes and exact rows in `nifty200_pit_piind_dated_identity_20260915.json` and `nifty200_pit_piind_dated_identity_retry_20260915.json`. These two sources are not counted in v7; their ingestion/rebuild is the next iteration. Do not merge the two ISINs by symbol similarity.

## Tests and safety checks

Regression before implementation: two failures and one pass in the new transcription tests; after implementation the combined transcription/public-dataset tests passed 34/34.

Final code verification v7: PIT 95 passed (3.56s); storage 9 passed (11.22s); full pytest 954 passed, 3 warnings (432.45s). Ruff passed. Mypy passed (57 source files). Pyright returned zero errors, 783 warnings. compileall and git diff --check passed. Exact commands and logs are in `nifty200_pit_blocker_verification_20260915_v7.json`. The earlier v6 full suite completed with 951 passed, 3 warnings (474.15s); it does not cover the transcription change.

All manifest-listed hashes were independently recomputed by the same agent and match; this is NOT independent QA. v7 interval SHA-256: `c7ea5bea4587639db654869bf02a5ad0aa49b5386a28269daa7f2a160c769edb`.

Dry-run importer: exit 1, REFUSED_AS_DESIGNED, `Manifest validation is not PASS; import refused`. No database touched. Independent QA NOT_ASSERTED; approved_for_import false; import approval NOT_GRANTED; Campaign Stage A BLOCKED.

Recommended commits, when the complete changes are reviewed: keep PIT extraction/evidence corrections and regression tests together; keep shared NSE calendar API fixes separately; do not include original-checkout Campaign governance changes. No recommendation to import or run research.
