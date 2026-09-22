# NIFTY-200 PIT symbol-transition resolution (2026-09-22)

## Scope and result

This report records the exact 31 category-H rows from `nifty200_pit_divergent_interval_forensics_20260922.csv`. The current authoritative worktree is the only project worktree used. No governance rule, software-hardening baseline, production DuckDB/WAL, Stage A, research, trading, broker API, push, or merge action was performed.

- Starting HEAD: `fa06120b033cafd28ce90a5fdc9e9ee255d3227e`.
- Rebuild verification HEAD: the local implementation state immediately before the final documentation commit; the final commit SHA is reported in the handoff.
- Baseline: 91 exact symbol intervals, 16 divergent intervals, 43 symbol-divergence records.
- H inventory: 31 raw records, 15 unique symbol transitions, 14 certified transition durable-ID groups.
- H disposition: all 31 records are represented by 15 evidence-backed transition groups; the 15 H-only intervals reconcile at durable-ID level. The raw symbol differences remain intentionally visible.
- Stage 2 residue: one interval, 12 records, six missing ADDs and six extra DROPs; no admissible NIFTY-200 event was found in the focused evidence set.
- Readiness: `EVENT_SOURCED_CONTRACT_NOT_READY`.

## Exact H records

The CSV companion contains the full per-record provenance, validity bounds, hashes, raw path, and resolution status. The rows below preserve every interval/role/symbol pair:

| interval | role | checkpoint symbol | paired symbol | proven transition | effective date | durable ID | status |
|---|---|---|---|---|---|---|---|
| 2013-08-30_to_2013-09-30 | MISSING | RAMCOCEM | MADRASCEM | MADRASCEM -> RAMCOCEM | 2013-09-30 | NSE-ISIN:INE331A01037 | RESOLVED_IDENTITY_ALIAS |
| 2013-08-30_to_2013-09-30 | EXTRA | MADRASCEM | RAMCOCEM | MADRASCEM -> RAMCOCEM | 2013-09-30 | NSE-ISIN:INE331A01037 | RESOLVED_IDENTITY_ALIAS |
| 2013-09-30_to_2013-10-31 | MISSING | SSLT | SESAGOA | SESAGOA -> SSLT | 2013-10-04 | NSE-ISIN:INE205A01025 | RESOLVED_IDENTITY_ALIAS |
| 2013-09-30_to_2013-10-31 | MISSING | UPL | UNIPHOS | UNIPHOS -> UPL | 2013-10-23 | NSE-ISIN:INE628A01036 | RESOLVED_IDENTITY_ALIAS |
| 2013-09-30_to_2013-10-31 | EXTRA | SESAGOA | SSLT | SESAGOA -> SSLT | 2013-10-04 | NSE-ISIN:INE205A01025 | RESOLVED_IDENTITY_ALIAS |
| 2013-09-30_to_2013-10-31 | EXTRA | UNIPHOS | UPL | UNIPHOS -> UPL | 2013-10-23 | NSE-ISIN:INE628A01036 | RESOLVED_IDENTITY_ALIAS |
| 2014-04-30_to_2014-05-30 | MISSING | CYIENT | INFOTECENT | INFOTECENT -> CYIENT | 2014-05-22 | NSE-ISIN:INE136B01020 | RESOLVED_IDENTITY_ALIAS |
| 2014-04-30_to_2014-05-30 | EXTRA | INFOTECENT | CYIENT | INFOTECENT -> CYIENT | 2014-05-22 | NSE-ISIN:INE136B01020 | RESOLVED_IDENTITY_ALIAS |
| 2015-04-30_to_2015-05-29 | MISSING | VEDL | SSLT | SSLT -> VEDL | 2015-05-07 | NSE-ISIN:INE205A01025 | RESOLVED_IDENTITY_ALIAS |
| 2015-04-30_to_2015-05-29 | EXTRA | SSLT | SESAGOA | SESAGOA -> SSLT | 2013-10-04 | NSE-ISIN:INE205A01025 | RESOLVED_IDENTITY_ALIAS |
| 2016-02-29_to_2016-03-31 | MISSING | RDEL | PIPAVAVDOC | PIPAVAVDOC -> RDEL | 2016-03-18 | NSE-ISIN:INE542F01012 | RESOLVED_IDENTITY_ALIAS |
| 2016-02-29_to_2016-03-31 | EXTRA | PIPAVAVDOC | RDEL | PIPAVAVDOC -> RDEL | 2016-03-18 | NSE-ISIN:INE542F01012 | RESOLVED_IDENTITY_ALIAS |
| 2016-03-31_to_2016-04-29 | EXTRA | RDEL | PIPAVAVDOC | PIPAVAVDOC -> RDEL | 2016-03-18 | NSE-ISIN:INE542F01012 | RESOLVED_IDENTITY_ALIAS |
| 2016-06-30_to_2016-07-29 | MISSING | BHARATFIN | SKSMICRO | SKSMICRO -> BHARATFIN | 2016-07-01 | NSE-ISIN:INE180K01011 | RESOLVED_IDENTITY_ALIAS |
| 2016-06-30_to_2016-07-29 | EXTRA | SKSMICRO | BHARATFIN | SKSMICRO -> BHARATFIN | 2016-07-01 | NSE-ISIN:INE180K01011 | RESOLVED_IDENTITY_ALIAS |
| 2018-12-31_to_2019-01-31 | MISSING | IDFCFIRSTB | IDFCBANK | IDFCBANK -> IDFCFIRSTB | 2019-01-16 | NSE-ISIN:INE092T01019 | RESOLVED_IDENTITY_ALIAS |
| 2018-12-31_to_2019-01-31 | EXTRA | IDFCBANK | IDFCFIRSTB | IDFCBANK -> IDFCFIRSTB | 2019-01-16 | NSE-ISIN:INE092T01019 | RESOLVED_IDENTITY_ALIAS |
| 2019-12-31_to_2020-01-31 | MISSING | NAMINDIA | RNAM | RNAM -> NAMINDIA | 2020-01-23 | NSE-ISIN:INE298J01013 | RESOLVED_IDENTITY_ALIAS |
| 2019-12-31_to_2020-01-31 | EXTRA | RNAM | NAMINDIA | RNAM -> NAMINDIA | 2020-01-23 | NSE-ISIN:INE298J01013 | RESOLVED_IDENTITY_ALIAS |
| 2020-01-31_to_2020-02-28 | MISSING | TATACONSUM | TATAGLOBAL | TATAGLOBAL -> TATACONSUM | 2020-02-27 | NSE-ISIN:INE192A01025 | RESOLVED_IDENTITY_ALIAS |
| 2020-01-31_to_2020-02-28 | EXTRA | TATAGLOBAL | TATACONSUM | TATAGLOBAL -> TATACONSUM | 2020-02-27 | NSE-ISIN:INE192A01025 | RESOLVED_IDENTITY_ALIAS |
| 2020-07-31_to_2020-08-31 | MISSING | COFORGE | NIITTECH | NIITTECH -> COFORGE | 2020-08-20 | NSE-ISIN:INE591G01017 | RESOLVED_IDENTITY_ALIAS |
| 2020-07-31_to_2020-08-31 | EXTRA | NIITTECH | COFORGE | NIITTECH -> COFORGE | 2020-08-20 | NSE-ISIN:INE591G01017 | RESOLVED_IDENTITY_ALIAS |
| 2020-09-30_to_2020-10-30 | MISSING | DHANI | IBVENTURES | IBVENTURES -> DHANI | 2020-10-28 | NSE-ISIN:INE274G01010 | RESOLVED_IDENTITY_ALIAS |
| 2020-09-30_to_2020-10-30 | EXTRA | IBVENTURES | DHANI | IBVENTURES -> DHANI | 2020-10-28 | NSE-ISIN:INE274G01010 | RESOLVED_IDENTITY_ALIAS |
| 2020-11-27_to_2020-12-31 | MISSING | INDUSTOWER | INFRATEL | INFRATEL -> INDUSTOWER | 2020-12-18 | NSE-ISIN:INE121J01017 | RESOLVED_IDENTITY_ALIAS |
| 2020-11-27_to_2020-12-31 | EXTRA | INFRATEL | INDUSTOWER | INFRATEL -> INDUSTOWER | 2020-12-18 | NSE-ISIN:INE121J01017 | RESOLVED_IDENTITY_ALIAS |
| 2020-12-31_to_2021-01-29 | MISSING | ATGL | ADANIGAS | ADANIGAS -> ATGL | 2021-01-13 | NSE-ISIN:INE399L01023 | RESOLVED_IDENTITY_ALIAS |
| 2020-12-31_to_2021-01-29 | EXTRA | ADANIGAS | ATGL | ADANIGAS -> ATGL | 2021-01-13 | NSE-ISIN:INE399L01023 | RESOLVED_IDENTITY_ALIAS |
| 2022-02-28_to_2022-03-31 | MISSING | ZYDUSLIFE | CADILAHC | CADILAHC -> ZYDUSLIFE | 2022-03-07 | NSE-ISIN:INE010B01027 | RESOLVED_IDENTITY_ALIAS |
| 2022-02-28_to_2022-03-31 | EXTRA | CADILAHC | ZYDUSLIFE | CADILAHC -> ZYDUSLIFE | 2022-03-07 | NSE-ISIN:INE010B01027 | RESOLVED_IDENTITY_ALIAS |

## Authoritative H evidence

- NSE `symbolchange.csv`: `https://nsearchives.nseindia.com/content/equities/symbolchange.csv`; SHA-256 `647cb988b3957e948b2847d740490ab340db5ecbc4b6195d0ed6ffe8180f0280`; retained at `data/raw/nifty200_pit_public_sources/raw/64/647cb988b3957e948b2847d740490ab340db5ecbc4b6195d0ed6ffe8180f0280.csv`; tier A1.
- Each promotion required an official OLD -> NEW relationship plus period-valid A1 identity rows on the applicable sides. Alias periods are bounded at the effective date; no current-only backdating or fuzzy/name continuity was used.
- The SESAGOA -> SSLT -> VEDL chain is one durable identity chain across two official transitions.
- CADILAHC -> ZYDUSLIFE is bounded at the 2022 transition using the period-valid INE010B01027 row; a separate 2013 INE010B01019 observation is retained and is not backdated into the later alias.
- Alias validation after rebuild: zero alias-overlap errors from the scoped H aliases.

## Replay checkpoints

| checkpoint | exact symbol-level intervals | raw symbol-divergence records | durable-ID interpretation |
|---|---:|---:|---|
| Baseline | 91 | 43 | 16 divergent intervals before identity correction |
| After H identity correction | 91 | 43 | 106 durable-ID exact intervals; 1 durable-ID-divergent interval remains |
| After A/B investigation | 91 | 43 | unchanged: no A/B event was admitted; 106 durable-ID exact, 1 divergent |

The symbol-level counts are intentionally unchanged because aliases do not rewrite historical checkpoint symbols or canonical event text. The durable-ID comparison resolves the 15 H-only intervals. Exact set equality remains required; count equality alone was not used.

## Stage 2 missing-event investigation

The remaining interval is `2021-08-31_to_2021-09-30`, with six ADD candidates (`ASTRAL`, `HINDCOPPER`, `INDIANB`, `IRFC`, `NATIONALUM`, `TATACOMM`) and six DROP candidates (`ABBOTINDIA`, `BBTC`, `CESC`, `GODREJAGRO`, `IBULHSGFIN`, `VGUARD`). The exact 12-row disposition is in `nifty200_pit_missing_event_resolution_20260922.csv`.

- August checkpoint: `https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataAug2021.zip`; SHA-256 `da623588b08cdf90cfd7bd7e66d083b88a34d767cf0ebdd10b599d65ef8f7796`; 200 members.
- September checkpoint: `https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataSep2021.zip`; SHA-256 `2ef5cba4356a50caefc3dfc1a04e38d3c753390bbb82ae1e29fb4055ddbbb8ee`; 200 members.
- Focused press release: `https://www.niftyindices.com/Press_Release/ind_prs15092021.pdf`; SHA-256 `56ab5fbf0a9e6e934ba0c4f1bc89444455e808a7b041ad58cab64ae52e9084db`. It contains several of these names in other-index sections (not NIFTY-200); `ASTRAL` and `TATACOMM` are absent. The scanned/blank August 23 release yielded no admissible NIFTY-200 event evidence.
- Result: zero A/B corrections admitted. Endpoint roster differences alone were not promoted to canonical ADD/DROP events. ABBOTINDIA is in the remaining B set and remains blocked because the focused release places it in another index section; OFSS is not in the remaining A/B set and keeps its pre-existing duplicate-event/manual-review disposition.

## Durable identity and artifact metrics

- H transition groups with official relation and bounded alias evidence: 15; H-only intervals reconciled by durable ID: 15.
- Artifact sources: 597; source-hash failures: 0; observations: 1,544; canonical events: 671; ADD/DROP: 327/344.
- Historical identity rows: 230,784; unresolved historical event identity cases: 1; certified historical-event identity resolution: 45.7902%.
- Intervals: 325; conflicts: 137 total, 1 HIGH, 136 CRITICAL; missing/non-200 checkpoints: 68; known_at unresolved: 0.
- 2012-01-02 anchor: `NOT_ESTABLISHED`; monthly blocker classification unchanged; calendar: `PARTIAL_NOT_CERTIFIED`.

## Validation and safety

- Full artifact rebuild completed with validation `BLOCKED`; source hash failures remained zero.
- Dry-run importer remained `REFUSED_AS_DESIGNED` because validation did not pass; production database and WAL were not touched.
- Focused identity tests passed after the correction (10 passed). Full PIT/storage/full-suite/static verification completed successfully before the final commit.
- No Stage A, backtest, research, paper/live trade, broker API, push, or merge occurred.

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
