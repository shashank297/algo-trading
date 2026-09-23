# NIFTY-200 PIT August 23 source resolution — 2026-09-23

## Decision

The official NSE Indices release explicitly proves the remaining 2021-09-30 NIFTY-200 event group. Page 14 has a dedicated `NIFTY 200` section: six exclusions and six inclusions. Page 1 states that the changes are effective from 30 September 2021, close of 29 September 2021.

The prior report-only A/B disposition is superseded for this exact source and interval. The broader PIT contract remains blocked.

## Scope and provenance

- Authoritative worktree: `C:\Python projects\algo trading-authoritative-evidence`.
- Starting HEAD: `c22a14094defb7e7b446753bce0e73b6b111f4ef`.
- Source present before this task: **YES**. It was already in the restored corpus and catalogue; no duplicate acquisition was performed.
- Source: [NSE Indices release dated 23 August 2021](https://niftyindices.com/Press_Release/ind_prs23082021.pdf).
- Local source: `data/raw/nifty200_pit_public_sources/press_releases/candidates/ind_prs23082021.pdf`.
- Catalogue retrieval timestamp: `2026-09-20T12:24:01.663136+00:00`.
- SHA-256: `c9b9feef248ca89f7d8c8f12009e3d5c409eb4d6c793eee061fb93bf0af1231e`.
- Size: 2,563,857 bytes; pages: 29; PDF is unencrypted and has no native text layer.
- The raw PDF remains unchanged. The source-bound derivative is `data/raw/nifty200_pit_public_sources/press_releases/candidates/ind_prs23082021.page14.txt`, with the parent SHA and page declaration embedded in its metadata.

The complete 29-page PDF was visually inspected. The six A and six B names also occur in other index sections, but those appearances were not used as NIFTY-200 evidence. The exact page-14 ledger is [nifty200_pit_august23_source_resolution_20260923.csv](nifty200_pit_august23_source_resolution_20260923.csv).

## Exact event set

### A — authoritative NIFTY-200 ADD

| symbol | durable instrument ID | page 14 action |
|---|---|---|
| ASTRAL | `NSE-ISIN:INE006I01046` | included |
| HINDCOPPER | `NSE-ISIN:INE531E01026` | included |
| INDIANB | `NSE-ISIN:INE562A01011` | included |
| IRFC | `NSE-ISIN:INE053F01010` | included |
| NATIONALUM | `NSE-ISIN:INE139A01034` | included |
| TATACOMM | `NSE-ISIN:INE151A01013` | included |

### B — authoritative NIFTY-200 DROP

| symbol | durable instrument ID | page 14 action |
|---|---|---|
| ABBOTINDIA | `NSE-ISIN:INE358A01014` | excluded |
| BBTC | `NSE-ISIN:INE050A01025` | excluded |
| CESC | `NSE-ISIN:INE486A01013` | excluded |
| GODREJAGRO | `NSE-ISIN:INE850D01014` | excluded |
| IBULHSGFIN | `NSE-ISIN:INE148I01020` | excluded |
| VGUARD | `NSE-ISIN:INE951I01027` | excluded |

All twelve canonical rows have announcement date `2021-08-23`, conservative `known_at` `2021-08-24T09:15:00+05:30`, effective date `2021-09-30`, source page `14`, source tier `A1`, extraction method `PDF_VISUAL_TRANSCRIPTION`, confidence `CERTIFIED`, and review status `ACCEPTED`. No symbol-derived durable identity was introduced.

## Cross-checks and event relationship

- The [15 September 2021 notice](https://www.niftyindices.com/Press_Release/ind_prs15092021.pdf), SHA-256 `56ab5fbf0a9e6e934ba0c4f1bc89444455e808a7b041ad58cab64ae52e9084db`, does not supersede the page-14 NIFTY-200 table. Its affected-name appearances are in other index sections; it contains no NIFTY-200 event for this twelve-record set.
- The [20 September 2021 notice](https://niftyindices.com/Press_Release/ind_prs20092021.pdf), SHA-256 `e32e8af37db78ec6e984af7d89fc1708ab8ce813fd4b7b17a3d62b246e6a84b2`, covers NIFTY Midcap Select and NIFTY SME Emerge changes and adds none of these twelve NIFTY-200 events.
- The [NIFTY-200 rebalancing schedule](https://www.niftyindices.com/resources/index-rebalancing-schedule) is consistent with a September semi-annual reconstitution, but the schedule itself is not event evidence.

## Parser and canonical changes

The native parser was not semantically wrong; it could not see this scanned/image-only PDF because `pypdf` returned blank page text. The narrow fix is fail-closed: when all native pages are blank, the pipeline may load a same-stem `.page14.txt` only when its metadata declares `VERIFIED_VISUAL_TRANSCRIPTION`, the exact parent SHA, and an in-range page. A mismatched sidecar raises an error. The regression test covers this path.

Canonical change: 12 new events — 6 ADD and 6 DROP. Existing canonical events, identities, and source bytes were not edited. Derived artifacts were rebuilt from the existing corpus.

## Replay result

The full 107-interval symbol replay was rerun from the regenerated canonical events. The targeted interval applied six ADD and six DROP events and exactly reproduced the 200-member September endpoint from the 200-member August endpoint.

| result | before | after |
|---|---:|---:|
| total intervals | 107 | 107 |
| symbol-exact intervals | 91 | 92 |
| symbol-divergent intervals | 16 | 15 |
| durable-ID exact intervals | 106 | 107 |
| durable-ID divergent intervals | 1 | 0 |
| target interval | `2021-08-31_to_2021-09-30` | exact after 12 events |

The remaining 15 symbol-level divergences are unrelated identity/event cases; they were not broadened or rewritten by this task. The former sole durable-ID divergence is resolved by the page-14 event group.

## Validation and readiness

Regenerated package metrics:

- sources: 597; source hash failures: 0;
- observations: 1,556; canonical events: 683;
- canonical ADD/DROP: 333 / 350;
- historical identity rows: 230,784; intervals: 332;
- conflicts: 132 total — 1 HIGH and 131 CRITICAL;
- blocker ledger: 203; missing/non-200 checkpoints: 68;
- anchor: `NOT_ESTABLISHED`;
- calendar: `PARTIAL_NOT_CERTIFIED`;
- validation: `BLOCKED`.

The importer dry-run was refused as designed with `Manifest validation is not PASS; import refused`; no production database or WAL was touched. No Stage A, research, backtest, paper/live trading, broker call, push, or merge occurred. Governance and the software-hardening baseline were not changed.

Verification:

- focused public-dataset/parser tests: 48 passed;
- full suite: 1,020 passed, 3 existing warnings;
- Ruff: clean;
- Mypy: clean with a writable cache;
- Pyright: 0 errors, 39 existing warnings;
- compileall: clean;
- `git diff --check`: clean.

The worktree’s unrelated pre-existing dirty and untracked reports were preserved. No push or merge was performed.

Readiness remains exactly:

`EVENT_SOURCED_CONTRACT_NOT_READY`

```text
NIFTY-200 PIT RECONSTRUCTION:
DATA EVIDENCE BLOCKED

INDEPENDENT PIT/DATA QA:
NOT ASSERTED

IMPORT APPROVAL:
NOT GRANTED

CAMPAIGN STAGE A:
BLOCKED
```
