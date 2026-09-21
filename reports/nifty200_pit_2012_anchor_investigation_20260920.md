# NIFTY-200 2012-01-02 anchor investigation

Date: 2026-09-20
Repository: `shashank297/algo-trading`
Worktree: `C:\Python projects\algo trading-authoritative-evidence`
Branch: `codex/nifty200-pit-authoritative-evidence`

## Decision

No direct authoritative full constituent roster valid on 2012-01-02 was found.
The backward candidate remains diagnostic only. The anchor therefore remains
`NOT_ESTABLISHED`, and the PIT validation remains fail-closed.

No new membership, identity, effective date, or announcement date was inferred
from price history, company names, B1 data, or a count of 200.

## Evidence searched

- [Official NSE Indices press-release archive](https://www.niftyindices.com/press-release), including the 2011-07-18 launch notice and the listed 2011-2012 change notices.
- [CNX 200 launch PDF](https://www.niftyindices.com/Press_Release/ind_prs18072011.pdf), SHA-256 `b5296626fd97331ed09d0da32822434d5b1e2afd92fe035f9702ebf730b155e3`.
- [Official index inclusion/exclusion workbook](https://archives.nseindia.com/content/indices/IndexInclExcl.xls), SHA-256 `8869bb7c4df67403131a494a8cc65509e80828f9438bc150b506cdbf55378046`.
- Official archived `ind_cnx200list.csv` captures already in the corpus. The earliest usable archived list is 2014-01-13; no 2012 capture was admitted.
- Official monthly archive family. The direct January 2012 URL
  `https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataJan2012.zip`
  returned the official site’s 404 page. No 2012-01-02 roster was present in the
  acquired corpus.
- The 2011-07-18 launch notice, official change notices, workbook, archived
  constituent-list captures, and the current Nifty 200 page were treated as
  evidence only; no page instructions were followed.

## Event chain around the proposed anchor

The table records the parser output from the existing A1/A2 corpus. A blank
event result means the official notice concerned another index and did not
assert a CNX/NIFTY-200 membership change.

| Publication date | Effective date | CNX/NIFTY-200 parser result | Source SHA-256 |
| --- | --- | --- | --- |
| 2011-07-18 | 2011-07-19 launch | No member rows; methodology and launch context only | `b5296626fd97331ed09d0da32822434d5b1e2afd92fe035f9702ebf730b155e3` |
| 2011-11-17 | 2011-11-22 | DROP `JINDALSAW`; ADD `APOLLOHOSP` | `d478721828e71fd43035721ce39dba853427ba87e30c8100941a40d865bcefc1` |
| 2011-12-01 | 2011-12-07 | DROP `IBREALEST`; ADD `REDINGTON` | `71bc2c9b334c760b3889e726b5016f925fcc60c816b3553e17c193ed12909fce` |
| 2011-12-12 | 2011-12-14 | DROP `AREVAT&D`; ADD `GSKCONS` | `a44f908e4e51b381fac49a73a8b1874f5d162b3fa2d97fd8c87ae78a233b6a59` |
| 2012-01-13 | 2012-02-24 | No CNX/NIFTY-200 rows; Midcap 50 notice | `fdce150922e484e500f2fdf7f0fee1d810024632ed67ec57218de970ddb8eceb` |
| 2012-02-29 | 2012-03-09 | No CNX/NIFTY-200 rows; S&P CNX 500 notice | `5a1ab5f0e5bb304c1d81d6e97d8f7d08f1ecf97e67a5b340751b7fffad7b19b2` |
| 2012-03-14 | 2012-04-27 | 12 DROP and 12 ADD rows | `e888c16134d0abfdfed880f8453dcee1556ee2816e02cc7137218f4781bf3e6f` |
| 2012-04-04 | 2012-04-09/12 | No CNX/NIFTY-200 rows; S&P CNX 500 notice | `778a1356675dde69d60dfbbc582e421be3da6ce8f79b87489de37de11a6fe1d1` |
| 2012-05-16 | 2012-05-21 | DROP `PATNI`; ADD `BRITANNIA` | `69178edc257ad769eeed77598740cc26ac173f8a5b822c2170fcd881e1cb647c` |
| 2012-08-16 | 2012-09-28 | 14 DROP and 14 ADD rows | `ae8b1817c0d6683eeb6d5196a1d537942697c45e3d1a20344c5474824b3a52df` |

The workbook independently contains the 2011-11-22, 2012-04-27, 2012-05-21,
and 2012-09-28 Nifty 200 change rows, but it is itself a change log and not a
complete 2012-01-02 membership roster. Its earliest Nifty 200 row is
2011-11-22.

## Backward proof attempt

The earliest complete acquired checkpoint is 2013-04-18, with 200 unique rows
and source SHA-256
`4942c0f021abcd6ed9702c343c2696ec44cfa8022c7e37448f8a78c075c4a16d`.

The existing diagnostic replay:

- reverses 80 canonical events to produce a 200-member candidate for
  2012-01-02;
- resolves all 200 candidate rows to a durable ID/ISIN in the diagnostic
  master, but does not make them authoritative;
- compares against 107 available later official checkpoints;
- obtains exact set equality for 5 checkpoints and set mismatches for 102;
- first checkpoint mismatch is 2013-09-30;
- replays 3,613 campaign sessions, with 2,941 non-200 diagnostic counts.

Count equality is not used as proof. Because the candidate depends on a later
checkpoint and the full historical chain is not independently complete, the
required status is `NOT_ESTABLISHED`, not
`BACKWARD_ANCHOR_PROOF_COMPLETE_PENDING_GOVERNANCE`.

## Causal interpretation of the 135 anchor rows

The ledger contains 135 `MISSING_INITIAL_ANCHOR` rows:

- 1 is the single root blocker for the absent authoritative 2012-01-02 set;
- 134 are downstream `REMOVAL_OF_ABSENT_MEMBER` state conflicts caused by
  starting replay without a certified initial set;
- 134 rows do not represent 134 independent missing anchor documents;
- no separate missing event-date root was reclassified as an anchor blocker by
  this investigation.

The rows remain unresolved because removing an instrument that is absent from
the uncertified diagnostic state would require assuming the very membership
state under review.

## Remaining identity cases

The following 15 observations remain manual-review identity gaps. Exact dated
first-party symbol/ISIN evidence or an explicit first-party identity/corporate-
action link is still required; name-only matching is insufficient.

| Date | Symbol | Company | Missing evidence |
| --- | --- | --- | --- |
| 2012-04-27 | — | Gujarat NRE Coke Ltd. | Dated official company-to-symbol/ISIN assertion |
| 2012-09-28 | — | Fortis Healthcare Ltd. | Dated official company-to-symbol/ISIN assertion |
| 2012-09-28 | — | Jammu & Kashmir Bank Ltd. | Period-valid symbol and ISIN assertion |
| 2012-09-28 | — | Shree Cement Ltd. | Dated official company-to-symbol/ISIN assertion |
| 2013-04-17 | — | Future Retail Ltd. | Historical Future-group instrument identity |
| 2013-09-27 | — | GVK Power & Infrastructures Ltd. | Dated identity distinguishing GVK entities |
| 2015-05-29 | — | Alstom T&D India Ltd. | Official continuity or corporate-action link |
| 2015-09-28 | — | Ajanta Pharmaceuticals Ltd. | Exact dated identity evidence |
| 2016-04-01 | — | Alstom T&D India Ltd. | Exact dated identity evidence |
| 2016-04-01 | — | Jain Irrigation Systems Ltd. | Ordinary/DVR-specific dated identity evidence |
| 2016-04-01 | — | National Buildings Construction Corporation Ltd. | Exact dated identity evidence |
| 2018-09-28 | — | HDFC Standard Life Insurance Company Ltd. | Official name-change/ISIN continuity evidence |
| 2019-09-27 | — | Reliance Nippon Life Asset Management Ltd. | Official name-change/ISIN continuity evidence |
| 2020-06-26 | — | Adani Gas Ltd. | Official name-change/ISIN continuity evidence |
| 2013-11-15 | `IBULHSGFIN` | Indiabulls Housing Finance Limited | First-party event/identity source for the exact date |

## Duplicate-event dispositions

- `ABBOTINDIA` ADD on 2022-03-31 remains `DUPLICATE_ADD` / `CRITICAL`.
  The official press release asserts the ADD, while the official March 2022
  checkpoint already contains the security. No prior DROP or effective-date
  correction was found in the acquired first-party chain.
- `OFSS` ADD on 2024-03-28 remains `DUPLICATE_ADD` / `CRITICAL`.
  The official press release asserts the ADD, while the historical checkpoint
  chain already contains OFSS. No authoritative prior DROP or date correction
  was found. Raw evidence is retained and no event was discarded.

## Build impact

No new admissible evidence was found, so no source was added and no builder
logic was changed. The measured before/after result is therefore unchanged:

- sources: 597; A1/A2/B1: 590/6/1; hash failures: 0;
- observations/canonical events: 1,544 / 671;
- ADD/DROP: 327 / 344;
- historical identities/unique instruments: 230,784 / 4,933;
- intervals: 325;
- conflicts: 137, including 1 HIGH and 136 CRITICAL;
- validation: `BLOCKED`.

## Artifacts and final state

- Validation: `artifacts/nifty200_pit_v1/validation_report.json`
- Blockers: `artifacts/nifty200_pit_v1/blocker_ledger.csv`
- Anchor checkpoint comparison: `reports/nifty200_pit_anchor_replay_checkpoint_comparison.csv`
- Anchor differences: `reports/nifty200_pit_anchor_replay_checkpoint_differences.csv`
- First divergence: `reports/nifty200_pit_anchor_replay_first_divergence.csv`
- Duplicate events: `reports/nifty200_pit_duplicate_event_forensics.csv`

No production DuckDB/WAL was touched. No import, Stage A, research,
backtesting, paper trading, broker API, or live trading operation was run.

Final status:

```text
NIFTY-200 PIT RECONSTRUCTION: DATA EVIDENCE BLOCKED
INDEPENDENT QA: NOT ASSERTED
IMPORT APPROVAL: NOT GRANTED
CAMPAIGN STAGE A: BLOCKED
```
