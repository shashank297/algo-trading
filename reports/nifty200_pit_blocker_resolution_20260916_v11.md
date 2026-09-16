# NIFTY-200 PIT empirical closure: v11

Build timestamp: **2026-09-16T02:03:22.063514+00:00**. Existing full builder rerun, exit 0 after 206.96 seconds. Dataset validation remains **BLOCKED**. A successful builder process is not a passing dataset.

This iteration repairs identity-certification and blocker-classification defects and acquires split evidence. It does not claim that the remaining evidence gaps are irreducible or that the overall objective is complete.

## Repository, scope and safety

- Branch: `codex/nifty200-pit-2012-anchor`.
- HEAD: `ea0f8bf9eb031abf3df9a7d46c568f72c0d5df31`, with ongoing uncommitted PIT changes.
- Freshly fetched origin/main: `a8f383149187b8d0bbfb23253ba81c464ec8563f`.
- Worktree: `C:\Users\Shukla\AppData\Local\Temp\nifty200-pit-security-master`.
- Original checkout: `C:\Python projects\algo trading`; its existing changes in `research.py`, `tests/test_campaign1_governance.py`, `reports/strategy_factory_hardened_baseline_20260906.md`, and untracked governance/baseline/reports remain preserved. They were not included in this work.
- No commit, push, merge, Campaign Stage A, strategy research/backtest, paper/live trading, broker API, production DB/WAL access or authoritative import was performed.
- Independent QA: **NOT_ASSERTED**. Import approval: **NOT_GRANTED**. `approved_for_import=false`.

## Actual measured build

| Measurement | v10 | v11 |
| --- | ---: | ---: |
| Catalogued source responses | 385 | 453 |
| A1 / A2 / B1 | 381 / 3 / 1 | 449 / 3 / 1 |
| Source hash errors | 0 | 0 |
| Event observations | 1,580 | 1,580 |
| Canonical events | 725 | 725 |
| ADD / DROP | 362 / 363 | 362 / 363 |
| Monthly snapshot rows | 21,650 | 21,650 |
| Snapshot dates | 108 | 108 |
| Literal 200-member checkpoints | 58 | 58 |
| Historical expected-count checkpoints, including evidenced 201-security DVR period | 108 | 108 |
| Missing/non-expected-count monthly checkpoints | 68 | 68 |
| Current security-master rows | 2,568 | 2,568 |
| Historical identity rows | 7,912 | 7,912 |
| Unique historical instruments | 3,451 | 3,451 |
| Durable-ID / ISIN resolution | 97.3132% / 97.3132% | 97.3132% / 97.3132% |
| Unresolved first-party identity observations | 32 / 1,191 | 32 / 1,191 |
| Constituent intervals | 354 | 354 |
| Campaign sessions checked | 3,613 | 3,613 |
| Minimum / maximum active membership | 0 / 128 | 0 / 128 |
| Sessions failing historical expected count | 3,613 | 3,613 |
| Canonical known_at unresolved | 0 | 0 |
| Conflicts: total / HIGH / CRITICAL | 129 / 1 / 128 | 129 / 1 / 128 |
| Validation | BLOCKED | BLOCKED |

The extra 68 catalogue records are **negative acquisition evidence**, not newly recovered membership lists: 53 valid archives contain no NIFTY-200 candidate member, and 15 ZIP URLs returned HTML. Their source tier describes origin, not usability; statuses are `NO_NIFTY200_CHECKPOINT` or `UNUSABLE_HTML_RESPONSE`. Zero hash failures means the saved bytes match their catalogue hashes, not that all responses contain valid data. No additional canonical events or intervals resulted from these responses.

The 32 unresolved identity observations are all `OFFICIAL_XLS` rows excluded by the existing redundant-observation rules. A read-only audit reproduced that exclusion for all 32 and retained exact rows in `nifty200_pit_unresolved_identity_cases_20260916.json`. This does not certify their identities, but they must not be counted as 32 independent missing membership events.

## Defects fixed and verified against regressions

1. **Manual-review aliases could become certified identities.** The resolver ignored alias confidence and converted a missing identifier to the string `"None"`. Three regression tests failed before the fix. It now fails closed on uncertified/missing alias identifiers and requires period validity; no fuzzy identity is promoted. The real canonical event hashes were unchanged by this fix.
2. **Abbreviated archive months were missed.** The monthly source matcher understood full month names but not names such as `indices_dataApr2022.zip`. Both forms are now recognised.
3. **A downloaded archive was treated as a found snapshot.** Source bytes are now checked for hash/integrity, HTML responses, absence of a target member, or a candidate member yielding no rows. Candidate-zero-row cases require extraction review rather than automatically being called confirmed parser defects.
4. **All absent-member removals were labelled initial-anchor gaps.** The ledger now distinguishes missing membership history from same-symbol/different-ISIN entry evidence. Prior canonical event hashes are retained in notes. Neither classification fabricates starting membership or links instruments automatically.

Six new blocker-classification regressions reproduced the previous incorrect classifications. Code changed in this iteration: `tools/nifty200_pit/instrument_resolver.py`, `tools/nifty200_pit/build_public_dataset.py`, `tests/test_nifty200_pit_identity.py`, `tests/test_nifty200_pit_public_dataset.py`, and new `tests/test_nifty200_pit_blocker_classification.py`. Generated reports and evidence are additional local outputs; earlier PIT changes remain uncommitted and preserved.

## Exact current blocker ledger

| Type | Rows | Meaning |
| --- | ---: | --- |
| COUNT_NOT_200 | 3,613 | Daily consequences of incomplete reconstruction; not independent missing documents |
| MISSING_MEMBERSHIP_HISTORY | 123 | No earlier same-symbol/index canonical entry; initial membership versus missing ADD is not established |
| HISTORICAL_ISIN_CHANGE | 5 | Earlier same-symbol ADD uses another ISIN; continuity is not yet represented |
| SOURCE_DOWNLOAD_FAILURE | 15 | January 2012-March 2013 URLs returned HTML instead of ZIP archives |
| MONTHLY_SNAPSHOT_MISSING | 54 | 53 monthly archives without target member plus one aggregate coverage conflict |
| **Total ledger rows** | **3,810** | Includes overlapping consequences and an aggregate |

All 128 affected removal securities/dates and original source lineage are present in the current `blocker_ledger.csv`. The previously frozen detailed audit remains `nifty200_pit_absent_member_root_cause_audit_20260915_v10.csv`; canonical event hashes are unchanged in v11.

The five identity cases remain J&KBANK (DROP 2016-04-01), KARURVYSYA (2018-09-28), NBCC (2020-06-26), NATCOPHARM (2022-03-31), and BATAINDIA (2024-03-28).

## Newly contacted identity sources and findings

Acquired **19 dated official NSE bhavcopies** and **10 official exchange/issuer documents or pages** into separate staging. Two company-hosted NATCO PDFs returned 404; their evidence was recovered from BSE/NSE-hosted copies. These 29 successful staged sources are **not included** in the 453-source build and have not changed membership or identity certification.

Exact contacted URLs, timestamps, local paths, SHA-256s and errors are in:

- `nifty200_pit_split_bhavcopies_20260916.json` and `_after.json`.
- `nifty200_pit_split_evidence_acquisition_20260916.json` and `_followup.json`.
- `nifty200_pit_isin_transition_evidence_20260916.csv`: six inspected transition cases, source pages, both dated NSE references, and remaining date-semantics cautions.

| Security | Old ISIN | New ISIN | Last checked old NSE reference | First checked new NSE reference |
| --- | --- | --- | --- | --- |
| J&KBANK | INE168A01017 | INE168A01041 | 2014-09-04 | 2014-09-05 |
| BATAINDIA | INE176A01010 | INE176A01028 | 2015-10-07 | 2015-10-08 |
| NATCOPHARM | INE987B01018 | INE987B01026 | 2015-11-26 | 2015-11-27 |
| NBCC | INE095N01015 | INE095N01023 | 2016-06-02 | 2016-06-03 |
| KARURVYSYA | INE036D01010 | INE036D01028 | 2016-11-17 | 2016-11-18 |
| NBCC | INE095N01023 | INE095N01031 | 2018-04-25 | 2018-04-26 |

These are **observed reference-file dates**, not invented legal effective dates or index events. The [Bata exchange notice](https://www.msei.in/SX-Content/Circulars/2015/October/Circular-3421.pdf), [Karur exchange notice](https://www.msei.in/SX-Content/Circulars/2016/November/Circular-4695.pdf), and [NBCC 2018 notice](https://www.msei.in/SX-Content/Circulars/2018/April/Circular-6260.pdf) explicitly connect old/new ISINs through splits. The [NATCO placement document](https://www.bseindia.com/downloads/ipo/20171214152921NATCOPHARM_PD.pdf) and [J&K annual report](https://www.bseindia.com/bseplus/AnnualReport/532209/5322090315.pdf) supply split evidence corroborated by dated NSE files.

Important: exchange ex-dates, record dates, issuer ISIN-allocation dates and NSE bhavcopy-reference changes are not interchangeable. Bata's annual report also states September 29, 2015 for ISIN change, whereas its exchange notice distinguishes October 7 ex-date and October 8 record date. NATCO's new NSE reference appears November 27, before its November 28 record date. Preserve these distinct assertions and establish the intended validity semantics before altering period-valid identity mappings. No similarity-based predecessor/successor merge was made.

## Artifacts, importer and checksum

Current package: `C:\Users\Shukla\AppData\Local\Temp\nifty200-pit-security-master\artifacts\nifty200_pit_v1`.

Frozen exact v11: `C:\Users\Shukla\AppData\Local\Temp\nifty200-pit-security-master\artifacts\iteration_blocker_classification_20260916_v11`. Earlier baseline/v10 packages were not overwritten.

Required evidence paths in both packages:

- `blocker_ledger.csv`
- `unresolved_gaps.csv`
- `validation_report.json`
- `evidence_manifest.json`
- `constituent_intervals.parquet`

Interval SHA-256: `68dfda87a69294d4db03ad7fa61f08a0f484d84a6d6c08ed6214c3b727a34da5` (unchanged).

All manifest-listed artifact hashes matched recomputation. Importer was rerun **DRY RUN ONLY**, exit 1, `REFUSED_AS_DESIGNED`: `Manifest validation is not PASS; import refused`. It did not touch a database. Measurements and exact command/output: `nifty200_pit_iteration_measured_20260916_v11.json`.

## Verification

PIT tests: **106 passed in 4.35s**. Storage tests: **9 passed in 13.93s**. Full suite: **965 passed, 3 warnings in 532.99s**, exit 0. Ruff passed; Mypy passed on 57 files; Pyright zero errors / 783 warnings; compileall passed; git diff --check passed. Exact commands, return codes and logs are recorded in `nifty200_pit_verify_20260916_v11.json` and its numbered logs. No build, test or acquisition process remains running for this iteration.

The ongoing tracked diff before this report was 23 files, 1,971 insertions and 142 deletions, excluding untracked files. This is the cumulative task diff, not only v11. Exact status/diff-stat and preserved original-checkout status are captured in `nifty200_pit_workspace_state_20260916_v11.json`.

## Remaining work and next action

Implement evidence-backed durable identity continuity for the six observed split transitions in the existing identity/replay path, preserving ISIN/date semantics and source hashes, then rebuild. Continue the missing initial-anchor/event search and alternate monthly-checkpoint acquisition. Complete checkpoint set reconciliation, event-date snapshot materialisation, period-valid identity and causality reviews, calendar certification, and blocker-ledger completeness. These are not all proven external/manual-only gaps.

Separate Campaign governance findings remain outside this PIT change: immutable family validation, the risk-policy hash mismatch, and baseline-v2 absence on main. Those findings were verified at the same unchanged origin/main commit in the September 15 governance report; no Campaign files were silently fixed here.

Recommended commits after review: isolate identity safety/blocker classification with regressions; keep subsequent source-backed continuity changes separate; keep Campaign governance separate. Do not commit raw/generated artifacts wholesale or production data/secrets.

NIFTY-200 PIT RECONSTRUCTION: **DATA EVIDENCE BLOCKED**  
INDEPENDENT QA: **NOT_ASSERTED**  
IMPORT APPROVAL: **NOT_GRANTED**  
CAMPAIGN STAGE A: **BLOCKED**
