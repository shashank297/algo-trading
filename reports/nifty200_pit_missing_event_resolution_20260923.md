# NIFTY-200 PIT unresolved A/B event investigation — 2026-09-23

## Scope and current set

This investigation starts from commit `1fcabc57384d5d5e88ff978d9730a7e3ed615e15` and uses only the existing authoritative PIT evidence worktree. It does not revisit the resolved H symbol transitions. The current replay reconciliation remains `reports/nifty200_pit_event_sourced_interval_reconciliation_20260921.csv`.

The exact post-H unresolved set is unchanged after re-reading the current artifacts:

- A (`MISSING_AUTHORITATIVE_ADD`): 6 records.
- B (`MISSING_AUTHORITATIVE_DROP`): 6 records.
- Unique affected securities: 12.
- Unique affected intervals: 1 — `2021-08-31_to_2021-09-30`.
- Previous checkpoint: 2021-08-31, 200 members.
- Next checkpoint: 2021-09-30, 200 members.
- Durable IDs are present in the current identity artifact, but membership-event causality is not certified.

The detailed per-record disposition is in `nifty200_pit_missing_event_resolution_20260923.csv`.

### Exact A records

| symbol | durable instrument | previous state | later state | narrow checkpoint-bounded ADD window |
|---|---|---|---|---|
| ASTRAL | `NSE-ISIN:INE006I01046` | absent | present | 2021-09-01 through 2021-09-30; scheduled effective date candidate 2021-09-30 |
| HINDCOPPER | `NSE-ISIN:INE531E01026` | absent | present | 2021-09-01 through 2021-09-30; scheduled effective date candidate 2021-09-30 |
| INDIANB | `NSE-ISIN:INE562A01011` | absent | present | 2021-09-01 through 2021-09-30; scheduled effective date candidate 2021-09-30 |
| IRFC | `NSE-ISIN:INE053F01010` | absent | present | 2021-09-01 through 2021-09-30; scheduled effective date candidate 2021-09-30 |
| NATIONALUM | `NSE-ISIN:INE139A01034` | absent | present | 2021-09-01 through 2021-09-30; scheduled effective date candidate 2021-09-30 |
| TATACOMM | `NSE-ISIN:INE151A01013` | absent | present | 2021-09-01 through 2021-09-30; scheduled effective date candidate 2021-09-30 |

### Exact B records

| symbol | durable instrument | previous state | later state | narrow checkpoint-bounded DROP window |
|---|---|---|---|---|
| ABBOTINDIA | `NSE-ISIN:INE358A01014` | present | absent | 2021-09-01 through 2021-09-30; scheduled effective date candidate 2021-09-30 |
| BBTC | `NSE-ISIN:INE050A01025` | present | absent | 2021-09-01 through 2021-09-30; scheduled effective date candidate 2021-09-30 |
| CESC | `NSE-ISIN:INE486A01013` | present | absent | 2021-09-01 through 2021-09-30; scheduled effective date candidate 2021-09-30 |
| GODREJAGRO | `NSE-ISIN:INE850D01014` | present | absent | 2021-09-01 through 2021-09-30; scheduled effective date candidate 2021-09-30 |
| IBULHSGFIN | `NSE-ISIN:INE148I01020` | present | absent | 2021-09-01 through 2021-09-30; scheduled effective date candidate 2021-09-30 |
| VGUARD | `NSE-ISIN:INE951I01027` | present | absent | 2021-09-01 through 2021-09-30; scheduled effective date candidate 2021-09-30 |

The interval boundary is the strongest date conclusion available from the two complete 200-member rosters. It does not prove that a NIFTY-200 event occurred on 2021-09-30.

## Per-record event trace

For every record, the current checkpoint artifacts show no raw event observation with a publication/effective date inside the 2021-09-01 through 2021-09-30 window and no current canonical ADD or DROP for that window. The previous and later membership states are therefore endpoint facts, not an admitted event.

The current canonical event chains, where present, are:

| symbol | current canonical events outside the disputed window |
|---|---|
| ASTRAL | 2024-09-30 DROP; publication 2024-09-25; known_at 2024-09-26 09:15 IST |
| HINDCOPPER | 2016-04-01 ADD; 2016-09-30 DROP; 2022-03-31 DROP |
| INDIANB | 2015-03-27 DROP; 2016-04-01 ADD; 2020-06-26 DROP |
| IRFC | 2022-03-31 DROP; 2023-03-31 ADD |
| NATIONALUM | 2012-04-27 DROP; 2014-09-19 ADD; 2015-09-28 DROP; 2016-04-01 ADD; 2021-03-31 DROP; 2023-03-31 DROP; 2025-03-28 ADD |
| TATACOMM | 2018-06-29 DROP |
| ABBOTINDIA | 2020-06-26 ADD; 2022-03-31 ADD retained as duplicate manual review; 2023-09-29 DROP |
| BBTC | 2018-12-28 ADD |
| CESC | 2018-02-05 DROP; 2019-09-27 ADD |
| GODREJAGRO | 2018-04-02 ADD |
| IBULHSGFIN | 2013-11-18 ADD |
| VGUARD | 2018-02-05 ADD |

For the accepted event rows, publication dates, conservative `known_at` timestamps, effective dates, source URLs, authority tiers, and source hashes remain in the existing `nifty200_pit_known_at_audit.csv`, canonical event artifacts, and restored source corpus. No existing canonical row was edited by this investigation.

The retained raw unresolved observations are not event evidence for this window. Where present, they are B1 discovery records from `https://raw.githubusercontent.com/deshpanda/nse-screener-data/main/reconstitution/events.parquet`, SHA-256 `2abc0e22e14305c83ed38d50f003c3b20a71f13555f0c8918d092c462598cb53`; they remain `NOT_CANONICALIZED`. The one A1 raw unresolved observation for IBULHSGFIN is also retained separately and does not establish a 2021 event.

## First-party search and source acceptance

The search followed the requested order: NSE Indices press releases and periodic notices first, then off-cycle/replacement and corporate-action categories, archived first-party pages, historical constituent files, and NSE historical security files for identity/date corroboration only. Company names were used only as discovery aids. Bhavcopy and B1 material were not used to certify membership.

The checked first-party evidence set is:

| source | SHA-256 | result |
|---|---|---|
| [August 2021 NIFTY-200 checkpoint](https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataAug2021.zip) | `da623588b08cdf90cfd7bd7e66d083b88a34d767cf0ebdd10b599d65ef8f7796` | complete 200-member endpoint |
| [September 2021 NIFTY-200 checkpoint](https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataSep2021.zip) | `2ef5cba4356a50caef3dfc1a04e38d3c753390bbb82ae1e29fb4055ddbbb8ee` | complete 200-member endpoint |
| [15 September 2021 replacements and criteria notice](https://www.niftyindices.com/Press_Release/ind_prs15092021.pdf) | `56ab5fbf0a9e6e934ba0c4f1bc89444455e808a7b041ad58cab64ae52e9084db` | affected names appear only in other index sections; no NIFTY-200 section or event for this set |
| [20 September 2021 replacements notice](https://www.niftyindices.com/Press_Release/ind_prs20092021.pdf) | `e32e8af37db78ec6e984af7d89fc1708ab8ce813fd4b7b17a3d62b246e6a84b2` | only NIFTY Midcap Select and NIFTY SME Emerge changes; no affected NIFTY-200 event |
| [23 August 2021 revision and replacements notice](https://www.niftyindices.com/Press_Release/ind_prs23082021.pdf) | `c9b9feef248ca89f7d8c8f12009e3d5c409eb4d6c793eee061fb93bf0af1231e` | no admissible affected NIFTY-200 event |
| [NIFTY-200 reconstitution schedule](https://www.niftyindices.com/resources/index-rebalancing-schedule) | page source retained in search record | confirms semi-annual last-working-day March/September schedule; schedule is not an event assertion |

The 15 September notice is useful negative evidence: it includes HINDCOPPER, INDIANB, IRFC, and NATIONALUM in NIFTY Midcap 150/other sections, and includes ABBOTINDIA, BBTC, CESC, GODREJAGRO, IBULHSGFIN, and VGUARD in non-NIFTY-200 sections. It does not name NIFTY-200 for these records. ASTRAL and TATACOMM are absent from that notice. The September 20 notice does not add a candidate pair. Consequently, no ADD/DROP pair can be promoted for NIFTY-200.

### Reconstitution pair analysis

No affected candidate has a first-party NIFTY-200 counterpart in the searched release set. The names that appear together in the 15 September notice are pairs or lists for NIFTY Midcap 150, NIFTY Smallcap, NIFTY India Manufacturing, or related indices. They cannot certify a NIFTY-200 ADD/DROP. No off-cycle, merger/demerger, delisting, or effective-date correction notice was found for this interval.

## ABBOTINDIA and OFSS

### ABBOTINDIA — 2022-03-31

`MANUAL_REVIEW_BLOCKED`.

The current chain contains an accepted 2020-06-26 ADD and a later accepted 2023-09-29 DROP. The 24 February 2022 first-party notice includes ABBOTINDIA in NIFTY-200 as an inclusion effective 2022-03-31, but the reconstructed interval is already active. The raw observation is retained as a duplicate ADD with source URL `https://www.niftyindices.com/Press_Release/ind_prs24022022_1.pdf`, SHA-256 `3091cf1c10b57bbae3b81645f5d91916a1af2bb7284902060f4640f7fb9fcd56`, publication date 2022-02-24, and known_at 2022-02-25 09:15 IST. No authoritative prior DROP, withdrawal, correction, or supersession closes the duplicate. The 15 September 2021 notice concerns other indices and does not resolve this 2022 duplicate.

### OFSS — 2024-03-28

`MANUAL_REVIEW_BLOCKED`.

The current chain contains an accepted 2021-03-31 DROP and 2022-03-31 ADD, followed by the 28 February 2024 first-party NIFTY-200 inclusion effective 2024-03-28. The raw 2024 ADD remains a duplicate/manual-review conflict. Source URL: `https://www.niftyindices.com/Press_Release/ind_prs28022024.pdf`, SHA-256 `5c70d043edde682a31fc5fa043a3b829a380fc9896de904bcb76d64b8319f698`, publication date 2024-02-28, known_at 2024-02-29 09:15 IST. No authoritative correction or supersession resolves it. OFSS is not in the current 2021 A/B set.

## Replay and checkpoint validity

No event group was resolved or admitted, so the required replay after each event group has an empty event-group set. The unchanged reconciliation is:

| stage | exact symbol-level intervals | divergent intervals | raw symbol-divergence records | durable-ID result |
|---|---:|---:|---:|---|
| Before this A/B task | 91 | 16 | 43 | 106 exact; 1 divergent after H identity resolution |
| After this A/B task | 91 | 16 | 43 | 106 exact; 1 divergent |

The two checkpoint sources are hash-valid, each reports 200 members, and the unresolved difference is not a parser truncation or count mismatch. The evidence issue is causal: the endpoint rosters show a transition but no admissible first-party NIFTY-200 event notice. No `CHECKPOINT_SOURCE_ISSUE` was assigned; the checkpoints remain valid endpoints with event causality unproven.

No newly found event improves backward-anchor completeness, changes the 2012/2013 blocker, or changes any of the 68 monthly blocker classifications.

## Artifact and validation impact

No new raw source was admitted, no canonical event changed, no identity changed, and no parser/canonicalization code changed. Therefore no full PIT artifact rebuild was required and prior artifacts were preserved.

| metric | before | after |
|---|---:|---:|
| sources | 597 | 597 |
| source hash failures | 0 | 0 |
| observations | 1,544 | 1,544 |
| canonical ADD/DROP events | 327 / 344 | 327 / 344 |
| historical identity rows | 230,784 | 230,784 |
| intervals | 325 | 325 |
| conflicts | 137 | 137 |
| blocker ledger rows | 208 | 208 |
| missing/non-200 checkpoints | 68 | 68 |

Validation remains `BLOCKED`; conflicts remain 137 total, including 1 HIGH and 136 CRITICAL. The 2012 anchor remains `NOT_ESTABLISHED`, the calendar remains `PARTIAL_NOT_CERTIFIED`, and readiness remains exactly:

`EVENT_SOURCED_CONTRACT_NOT_READY`

## Verification and safety

This was a report-only evidence disposition. No source bytes, canonical events, derived intervals, governance, or software-hardening baseline were changed. Because no code or evidence source was admitted, no rebuild was performed. The implementation remains unchanged from commit `1fcabc5` and was re-verified for this handoff:

- PIT tests: 119 passed; storage tests: 9 passed; full suite: 1,019 passed with 3 existing warnings.
- Ruff: clean; implementation Mypy: clean; Pyright: 0 errors and 27 existing warnings; compileall: clean; diff check: clean.
- The importer dry-run remains `REFUSED_AS_DESIGNED` with `Manifest validation is not PASS; import refused`; production database and WAL were not touched.
- No Stage A, research, backtest, paper/live trading, broker API, push, or merge activity occurred.

Starting HEAD: `1fcabc57384d5d5e88ff978d9730a7e3ed615e15`.

Prior report-only commit: `a363523` (`Document-unresolved-PIT-A-B-investigation`). This metadata amendment is the current final local report update; the final HEAD is the containing commit. No push or merge was performed. Existing unrelated dirty/untracked reports remain preserved.

## Governance state

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
