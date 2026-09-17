# NIFTY-200 PIT empirical closure: v12

The full existing builder completed at 2026-09-16T05:28:49.500952+00:00, exit 0 after 210.72 seconds. Automated data validation remains **BLOCKED**. Five real replay conflicts were resolved; no membership assertions were added, removed or fabricated.

## Exact before/after

| Measurement | v11 | v12 |
| --- | ---: | ---: |
| Sources | 453 | 471 |
| A1 / A2 / B1 | 449 / 3 / 1 | 467 / 3 / 1 |
| Source hash failures | 0 | 0 |
| Observations | 1,580 | 1,580 |
| Canonical events: ADD / DROP | 362 / 363 | 362 / 363 |
| Snapshot rows / dates | 21,650 / 108 | 21,650 / 108 |
| Valid historical expected-count checkpoints | 108 | 108 |
| Missing monthly checkpoints | 68 | 68 |
| Historical identity rows | 7,912 | 7,912 |
| Unique historical instruments | 3,451 | 3,445 |
| Constituent intervals | 354 | 354 |
| Conflicts: CRITICAL / HIGH | 128 / 1 | 123 / 1 |
| Ledger rows, including repeated daily consequences | 3,810 | 3,805 |
| Campaign sessions / sessions failing expected count | 3,613 / 3,613 | 3,613 / 3,613 |
| Active membership range | 0-128 | 0-123 |
| Canonical known_at unresolved | 0 | 0 |

Current security-master rows remain 2,568. Durable-ID and ISIN resolution remain 97.3132% of 1,191 nonsuperseded first-party event observations; all 32 unresolved observations were previously demonstrated to be redundant workbook rows, not 32 additional independent membership gaps. Literal 200-member checkpoints: 58; an additional 50 official checkpoints have the documented historical 201-security DVR count.

## Root cause and actual closure

A documented stock split changed an equity's ISIN, while the replay used `NSE-ISIN:<ISIN>` as though it were an immutable equity identifier. The later DROP therefore failed to close the earlier ADD. Six exact continuity links (NBCC has two) now require a hash-verified first-party split document and matching EQ rows in before/after dated NSE reference files. They link durable instrument identities only; they do not rewrite ISINs, effective/announcement dates, knowledge times, confidence or raw source assertions.

| Resolved absent-member DROP | Effective date |
| --- | --- |
| J&KBANK | 2016-04-01 |
| KARURVYSYA | 2018-09-28 |
| NBCC | 2020-06-26 |
| NATCOPHARM | 2022-03-31 |
| BATAINDIA | 2024-03-28 |

The full before/after audit confirms unchanged underlying assertions for all 1,580 observations and 725 canonical events. Derived hashes changed for five canonical events; one superseded NBCC observation ID also changed because it is derived from the resolved identity. Exact lineage is preserved in the continuity audit and frozen v11/v12 packages. No new conflicts appeared. Closing formerly orphaned intervals lowers the maximum active count by five; this is removal of stale membership, not loss of valid constituents.

The 18 newly merged sources were already acquired in staging: six BSE/MSE documents and twelve dated official NSE bhavcopies. All were re-hashed before integration. Exact URLs/hashes are in `nifty200_pit_split_source_merge_20260916_v12.json` and the package's `identity_continuity_evidence.json`. There were no new source downloads in this build. Existing source bytes, ISIN-validity assertions and uncertainty about differing ex/record/reference dates remain intact; this change does not certify those date semantics.

## Remaining blockers and discovered audit defect

The current ledger contains 123 `MISSING_MEMBERSHIP_HISTORY`, 15 `SOURCE_DOWNLOAD_FAILURE`, 54 `MONTHLY_SNAPSHOT_MISSING` (53 individual months plus one aggregate), and 3,613 daily count failures. The initial 2012-01-02 anchor is still not established. The 68 monthly gaps, incomplete calendar certification, full member-set reconciliation, period-valid identity review and other audit deliverables remain open; they have not all been proved irreducible external gaps.

Read-only inspection reproduced another real defect: `_valid_checkpoint_groups` casefolds symbols but tests an uppercase `TATAMTRDVR` literal, wrongly excluding 50 otherwise valid 201-security checkpoints dated 2016-04-29 through 2020-05-29. This v12 package preserves that failure state. The next iteration must fix and regression-test it, then rerun; a source's correct member count is not proof of reconstruction set equality. Exact excluded dates and source hashes are in `nifty200_pit_checkpoint_case_defect_20260916_v12.json`.

## Artifacts and safety

Frozen package: `artifacts/iteration_isin_continuity_20260916_v12`. Current package at completion: `artifacts/nifty200_pit_v1`. Full measurements: `reports/nifty200_pit_iteration_measured_20260916_v12.json`. Assertion/conflict comparison: `reports/nifty200_pit_continuity_empirical_audit_20260916_v12.json`.

Constituent interval SHA-256: `189da74ad6aac6e0c327ee10b3a6f9f6f56d8646f30d91feefadaa5a60bd0c59`. Every manifest-listed hash matched. Importer dry-run exit 1: `Manifest validation is not PASS; import refused`. Database untouched. Independent QA **NOT_ASSERTED**; `approved_for_import=false`; import approval **NOT_GRANTED**; Campaign Stage A **BLOCKED**.

Branch `codex/nifty200-pit-2012-anchor`; HEAD `ea0f8bf9eb031abf3df9a7d46c568f72c0d5df31`; origin/main tracking ref `a8f383149187b8d0bbfb23253ba81c464ec8563f`. No commit/push/merge or governance fixes performed. Original checkout's existing governance work remains preserved. Scope for this iteration: continuity projection and its audit outputs in the existing builder, historical-ISIN-safe resolver deduplication, `test_nifty200_pit_isin_continuity.py` and an identity regression; no replacement pipeline.

## Verification

PIT: 112 passed in 4.20s. Storage: 9 passed in 16.09s. Ruff passed. Mypy passed on 57 files. Pyright: zero errors, 783 warnings. Compileall and git diff --check passed. Full suite: **971 passed, 3 warnings in 531.68s**, exit 0. Exact commands and terminal results are in `nifty200_pit_verify_20260916_v12.json`. These results do not establish data completeness or independent QA.
