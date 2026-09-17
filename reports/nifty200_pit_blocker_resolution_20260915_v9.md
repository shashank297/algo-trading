# NIFTY-200 PIT empirical closure iteration v9

Build timestamp: 2026-09-15T15:50:08.444835+00:00.

NIFTY-200 PIT RECONSTRUCTION: DATA EVIDENCE BLOCKED.
INDEPENDENT QA: NOT_ASSERTED.
IMPORT APPROVAL: NOT_GRANTED.
CAMPAIGN STAGE A: BLOCKED.

This is an intermediate measured result. Remaining work has not been demonstrated irreducible; do not treat this report as task completion.

## Repository and preservation

- Worktree: `C:\Users\Shukla\AppData\Local\Temp\nifty200-pit-security-master`.
- Branch: `codex/nifty200-pit-2012-anchor`.
- HEAD: `ea0f8bf9eb031abf3df9a7d46c568f72c0d5df31` plus uncommitted PIT changes.
- Freshly fetched origin/main: `a8f383149187b8d0bbfb23253ba81c464ec8563f`.
- Original checkout governance changes remain untouched: research.py, tests/test_campaign1_governance.py, hardened baseline report, baseline_v2, and post-merge verification documents.
- No commit, push or merge was performed in these iterations. No production DB/WAL access, research configuration, broker call, trading, Stage A, or authoritative import was performed.
- Frozen packages: `artifacts/iteration_scanned_notice_20260915_v7`, `artifacts/iteration_dated_piind_20260915_v8`, `artifacts/iteration_ireda_revocation_20260915_v9`. All earlier blocked packages remain intact.

## Actual build measurements

| Metric | v6 baseline | v7 scanned notice | v8 dated identities | v9 revocation |
| --- | ---: | ---: | ---: | ---: |
| Source count | 379 | 379 | 381 | 381 |
| A1 / A2 / B1 | 375 / 3 / 1 | 375 / 3 / 1 | 377 / 3 / 1 | 377 / 3 / 1 |
| Source hash failures | 0 | 0 | 0 | 0 |
| Event observations | 1567 | 1579 | 1579 | 1580 |
| Canonical events | 713 | 725 | 725 | 725 |
| ADD / DROP | 356 / 357 | 362 / 363 | 362 / 363 | 362 / 363 |
| Intervals | 345 | 352 | 353 | 354 |
| Conflicts | 142 | 138 | 135 | 134 |
| HIGH / CRITICAL | 1 / 141 | 1 / 137 | 1 / 134 | 1 / 133 |
| Duplicate-add conflicts | 3 | 2 | 1 | 0 |
| Ledger rows | 3823 | 3819 | 3816 | 3815 |
| Validation | BLOCKED | BLOCKED | BLOCKED | BLOCKED |

v9 snapshot rows: 21,650 across 108 dates. There are 58 literal 200-security checkpoints and 50 evidenced 201-security DVR-era checkpoints, for 108 matching the implemented historical count rule. Missing monthly checkpoints: 68. A matching count does not prove snapshot/replay set agreement.

Current security-master rows: 2,568. Historical identity rows: 7,820. Unique historical instruments: 3,451. First-party non-superseded event observations: 1,191; unresolved identity observations: 32. Durable-ID and ISIN resolution each: 97.3132%. These describe resolver output, not independent certification of historical identity validity periods.

Campaign decision sessions checked: 3,613. Minimum active constituent count: 0; maximum: 133. All 3,613 fail the historical expected-count rule. The existing NSE calendar implementation has eight source-bound overrides, but its full campaign holiday/special-session audit remains PARTIAL_NOT_CERTIFIED; do not claim 3,613 is a fully independently verified session denominator.

Canonical known_at unresolved count: 0. This does not prove causality for excluded observations or certify the entire calendar. Contradicted B1 observations: 19, retained unchanged in the source-observation artifact and excluded from reconciliation with explicit evidence dispositions. No B1 row was promoted.

## Closures supported by real evidence

### Scanned August 2021 notice

The [August 23, 2021 official release](https://www.niftyindices.com/Press_Release/ind_prs23082021.pdf), SHA `c9b9feef248ca89f7d8c8f12009e3d5c409eb4d6c793eee061fb93bf0af1231e`, has no native text. Original rendered page 1 provides announcement and effective dates; page 14 gives six NIFTY 200 removals and six additions, effective September 30, 2021.

DROP: ABBOTINDIA, BBTC, CESC, GODREJAGRO, IBULHSGFIN, VGUARD.
ADD: ASTRAL, HINDCOPPER, INDIANB, IRFC, NATIONALUM, TATACOMM.

The bundled visual transcription is hash-bound to the original PDF, explicitly identifies Codex extraction, and does not claim independent QA. The ordinary parser/resolver handles it. Date page, event page, raw row and derivative SHA are retained. `pdf_transcriptions.json` is manifest-hashed. Twelve canonical events were recovered and four conflicts disappeared. The exact new events are in `nifty200_pit_recovered_events_20260915_v7.csv`.

The native-empty PDF inventory found this single wholly native-empty release in the acquired press-release corpus. This does not rule out partial extraction defects elsewhere.

### Dated identity evidence

Official [September 28, 2015 bhavcopy](https://nsearchives.nseindia.com/content/historical/EQUITIES/2015/SEP/cm28SEP2015bhav.csv.zip), SHA `3991b0c15f3d11e9eef4cad0dd70c906f9ccbda84cf8078270e40b9338862443`, and [September 30, 2016 bhavcopy](https://archives.nseindia.com/content/historical/EQUITIES/2016/SEP/cm30SEP2016bhav.csv.zip), SHA `85d073115ed588f5a00e0e511f852c9259eef2d305cdc55196b566637fce6b57`, establish PIIND normal-equity ISIN INE603J01030 on those dates. The previous reconstruction assigned the corresponding additions INE603J01022.

Adding these sources to the existing catalogue corrected both PIIND additions and AJANTPHARM's September 2015 identity. Three canonical event hashes changed, with no net event-count change; three conflicts disappeared. The bhavcopy mappings remain day-scoped and are not index-membership evidence. No ISINs were merged by symbol similarity. Exact old/new events and source rows are in the v8 recovered/replaced event CSVs and the PIIND acquisition JSON reports. The initial 2015 archives host 403 was preserved; nsearchives supplied the official file.

### IREDA revocation and BSE replacement

The [March 19, 2024 correction](https://www.niftyindices.com/Press_Release/ind_prs19032024.pdf), SHA `1bef44dabdf594b9390b15329de1d9f38a8ab96af2abea243e99311b6d61587e`, explicitly revokes the February 28 announcement of IREDA's March inclusion. Its page 2 multi-index table adds BSE to NIFTY 200 effective March 28.

The existing parser now extracts bounded multi-index grids and ignores revoked actions as new membership events. A source-byte-verified disposition marks only IREDA's original NIFTY 200 ADD for March 28 as superseded. The September IREDA addition, unrelated symbols, DROP actions and other indices are untouched. Original and B1 assertions remain in the evidence. BSE's canonical row retains page 2 and the March 19 announcement. No artificial IREDA DROP was created. This removed the last duplicate-add conflict.

## Exact remaining-gap audit

The current ledger contains 3,613 COUNT_NOT_200 consequences, 69 MONTHLY_SNAPSHOT_MISSING entries (68 months plus one aggregate), and 133 removals labelled MISSING_INITIAL_ANCHOR. These are not 3,815 independent evidence gaps.

All 133 removal conflicts are now traced in `nifty200_pit_absent_member_root_cause_audit_20260915_v9.csv`, one row per security/date with source hash and prior ADD lineage:

- 123 securities have no prior canonical ADD: missing initial membership versus a missing historical event is not yet established.
- 10 have a prior same-symbol ADD under a different instrument/ISIN: J&KBANK (DROP 2016-04-01), KSCL (2016-04-01), KARURVYSYA (2018-09-28), GRUH (2019-09-27), NBCC (2020-06-26), AMARAJABAT (2022-03-31), NATCOPHARM (2022-03-31), BATAINDIA (2024-03-28), NAVINFLUOR (2024-03-28), BERGEPAINT (2024-09-30).

The observed identity discontinuity is proven in the artifacts; whether each is an actual historical ISIN transition or a resolver validity-period defect still requires dated first-party evidence. The broad initial-anchor ledger label must be refined, not accepted as a proved cause. No fuzzy certification or predecessor/successor merging is justified.

The monthly source audit contacted/probed all 68 missing monthly URLs (including reuse of three downloads from the same investigation):

- January 2012 through March 2013: 15 HTTP-200 responses contain HTML titled Error 404, not ZIP data.
- April 2022 through August 2026: 53 valid ZIP archives list other indices and no NIFTY-200 table.

These are distinct evidence failures, not 68 parser errors. Full URLs, hashes, archive member lists, status and required action are retained in `nifty200_pit_monthly_source_inventory_20260915.json` and `nifty200_pit_monthly_gap_evidence_20260915.csv`. These negative-evidence downloads remain separately staged under `artifacts/monthly_acquisition_20260915`; they are NOT included in v9's 381-source count. No claim is made that alternative free/archived NIFTY-200 checkpoints do not exist.

Additional unresolved requirements: proven January 2012 anchor, historical identity/symbol continuity, exact reconciliation against all 108 checkpoints (the current anchor diagnostic compares only 58 and ignores some renames), missing narrative event extraction, complete calendar audit, and any remaining known-at/manual review. Event-date snapshot materialization and ledger completeness still need verification. Campaign governance remains separate and blocked.

## Artifacts and import safety

Current package: `artifacts/nifty200_pit_v1/`. Exact v9 frozen package: `artifacts/iteration_ireda_revocation_20260915_v9/`.

Required paths present include `blocker_ledger.csv`, `unresolved_gaps.csv`, `validation_report.json`, `evidence_manifest.json`, `constituent_intervals.parquet`, source catalogue, observations, canonical events, identity tables, intervals, snapshots, conflict/discrepancy reports, coverage matrices, known-at audit, checksums and dry-run output. Presence does not prove completeness; notably event-date snapshots remain an outstanding content requirement.

Interval SHA-256: `299bf3ed7da0a9230f867b17dce9fee7d2e5aa890300aced5206873681899372`.
All manifest-listed artifact hashes match recomputation by the same agent; this is not independent QA.

Dry-run importer: exit 1, REFUSED_AS_DESIGNED, `Manifest validation is not PASS; import refused`. No database touched. `approved_for_import=false`; independent QA NOT_ASSERTED; import approval NOT_GRANTED.

## Verification and changes

The two revocation/grid regressions failed before implementation and passed afterward; the focused parser/public-dataset suite then passed 43 tests. Completed v9 verification: PIT 97 passed (3.55s), storage 9 passed (13.72s), full pytest 956 passed / 3 warnings (471.06s), Ruff passed, Mypy passed (57 files), Pyright zero errors/783 warnings, compileall passed, git diff --check passed. Exact commands and outputs are in the versioned v9 verification JSON and logs.

Changes in v7-v9: tools/nifty200_pit/ocr.py, tools/nifty200_pit/parse_pdf.py, tools/nifty200_pit/build_public_dataset.py, the hash-named transcription JSON, tests/test_nifty200_pit_transcription.py, parser/public-dataset regression tests, and versioned evidence/reports. Prior PIT/calendar changes are retained, not silently attributed to this iteration. The current tracked diff across the ongoing task is 23 files, 1,872 insertions, 126 deletions; untracked evidence/reports/tests are additional. Exact git status and diff-stat output are in `nifty200_pit_workspace_state_20260915_v9.json`.

Recommended commits after review: PIT extraction and evidence corrections with regression tests; shared NSE calendar API fixes separately; empirical reports separately if useful. Do not include the original checkout's uncommitted Campaign governance changes. Do not commit databases, secrets, raw runtime logs or wholesale generated artifacts without reviewing repository policy.

## Exact next action

Newly acquired dated NSE bhavcopies establish KSCL as INE455I01029 on 2014-09-19, GRUH as INE580B01029 on 2015-03-27, AMARAJABAT as INE885A01032 on 2013-04-01, and NAVINFLUOR as INE048G01026 on 2020-09-25. All four differ from the corresponding current reconstruction's ADD identities and match its later DROP identities. The four raw sources and exact hashes are staged separately and recorded in `nifty200_pit_identity_continuity_probe_20260915.json`; they are not included in v9's 381 sources. Incorporate these dated identities using the existing pipeline and rebuild against frozen v9.

Then incorporate the newly evidenced distinction between absent tables, invalid HTML downloads, missing initial/event predecessors and identity discontinuities into the existing blocker ledger. Continue dated identity/official split-change evidence and alternative archived initial/monthly constituent-source investigation. This is continued closure work, not a recommendation to import or start Campaign Stage A.
