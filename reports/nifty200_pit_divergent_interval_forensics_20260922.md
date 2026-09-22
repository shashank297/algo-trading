# NIFTY-200 divergent interval forensics -- 2026-09-22

**Scope.** Report-only forensic analysis of the 16 checkpoint-to-checkpoint intervals where the existing event-sourced reconciliation has `symbol_set_equality_diagnostic=NO`. Work was performed only in `C:\Python projects\algo trading-authoritative-evidence`, on branch `codex/nifty200-pit-authoritative-evidence`. No source bytes, canonical events, identity rows, software, production database/WAL, or governance rules were changed.

**Decision.** `EVENT_SOURCED_CONTRACT_NOT_READY`. All 107 intervals have `identity_complete=NO` and `exact_set_equality=NOT_CERTIFIABLE`; 91 intervals are symbol-equal diagnostically, 16 diverge, and the 16 contain 43 divergence occurrences. The 43 detailed records are in the companion CSV.

## Required governance state

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

## 1. Exact divergent intervals and endpoint evidence

| # | Earlier | Later | Earlier count | Later count | Replay count | Missing symbols | Extra symbols | Later checkpoint source | Later SHA-256 |
|---:|---|---|---:|---:|---:|---|---|---|---|
| 1 | 2013-08-30 | 2013-09-30 | 200 | 200 | 200 | RAMCOCEM | MADRASCEM | https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataSep2013.zip | 9527c053b55c0947d5709f568ac0f12e5a3ebdd73fc0dad941f448ca5ea1abfb |
| 2 | 2013-09-30 | 2013-10-31 | 200 | 200 | 200 | SSLT;UPL | SESAGOA;UNIPHOS | https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataOct2013.zip | a6b5e1db29dd4d6dc215be54abcfcecc51b25b9993a0ac55cf24587fca191b9a |
| 3 | 2014-04-30 | 2014-05-30 | 200 | 200 | 200 | CYIENT | INFOTECENT | https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataMay2014.zip | 3686404c96b45f0cb3a0c9eb80027142cba84f32e92f4985ce22e68c82c23908 |
| 4 | 2015-04-30 | 2015-05-29 | 200 | 200 | 200 | VEDL | SSLT | https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataMay2015.zip | 094e9a7efb4e38d84b3c69e0abd029b6571af6814fe8826bef4187b375525f1f |
| 5 | 2016-02-29 | 2016-03-31 | 200 | 200 | 200 | RDEL | PIPAVAVDOC | https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataMar2016.zip | b0f6a0c799f058e23da93c0c7f26e47d45e25b29df814e19c3742a6421539c3e |
| 6 | 2016-03-31 | 2016-04-29 | 200 | 201 | 202 | -- | RDEL | https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataApr2016.zip | 85ecfe81fd09d784f824484632c36a83ae91cc549f1fa32a51140a4b0032cbeb |
| 7 | 2016-06-30 | 2016-07-29 | 201 | 201 | 201 | BHARATFIN | SKSMICRO | https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataJul2016.zip | cb0f3c78c9052e199c5733510e7028bb6f54ca2d006dcf6e4a4eefe1d4995043 |
| 8 | 2018-12-31 | 2019-01-31 | 201 | 201 | 201 | IDFCFIRSTB | IDFCBANK | https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataJan2019.zip | bf5e8acd6dcba671013874e21058cba19379fb83b221931628ef90d111d81f3d |
| 9 | 2019-12-31 | 2020-01-31 | 201 | 201 | 201 | NAMINDIA | RNAM | https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataJan2020.zip | 3392685a8c0a3e06ef313354efe174e60c3d4dd62683f7e05cee3c436b62b721 |
| 10 | 2020-01-31 | 2020-02-28 | 201 | 201 | 201 | TATACONSUM | TATAGLOBAL | https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataFeb2020.zip | f79792707dbacba304fa94b0006eee80644b4314c4279cebbf2aa2db4f6c12eb |
| 11 | 2020-07-31 | 2020-08-31 | 200 | 200 | 200 | COFORGE | NIITTECH | https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataAug2020.zip | bbc2408d0c3eaae9a2c2421eda33cb383945cd7b7cab7e8d173365c44de88d4f |
| 12 | 2020-09-30 | 2020-10-30 | 200 | 200 | 200 | DHANI | IBVENTURES | https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataOct2020.zip | 62079b5a9c43c475f7f558453a4e27461cdf0ef06c056a521f852a4d85bde0c4 |
| 13 | 2020-11-27 | 2020-12-31 | 200 | 200 | 200 | INDUSTOWER | INFRATEL | https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataDec2020.zip | 61922f25601735aeb00d534f04de99924607cc4f51ad1cc8777f61720af3ba0c |
| 14 | 2020-12-31 | 2021-01-29 | 200 | 200 | 200 | ATGL | ADANIGAS | https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataJan2021.zip | c078a1b9f76004b113af682d30fe1107e30795860d9ad3eab3ad0e3638a58a06 |
| 15 | 2021-08-31 | 2021-09-30 | 200 | 200 | 200 | ASTRAL;HINDCOPPER;INDIANB;IRFC;NATIONALUM;TATACOMM | ABBOTINDIA;BBTC;CESC;GODREJAGRO;IBULHSGFIN;VGUARD | https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataSep2021.zip | 2ef5cba4356a50caefc3dfc1a04e38d3c753390bbb82ae1e29fb4055ddbbb8ee |
| 16 | 2022-02-28 | 2022-03-31 | 200 | 200 | 200 | ZYDUSLIFE | CADILAHC | https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataMar2022.zip | 44a182c845eac8ddd6864abe535d02c6ce9bdecc0adbf11a16e25133cc44b969 |

Replay count is diagnostic only; it does not establish durable-ID equality. The 201-member later checkpoints are retained as observed and were not coerced to 200. The companion CSV carries both endpoint source URLs and hashes for every record.

## 2. Root-cause classification of all 43 divergence occurrences

| Category | Meaning in this analysis | Occurrences |
|---|---|---:|
| A | Missing authoritative ADD in the admitted canonical event chain. | 6 |
| B | Missing authoritative DROP in the admitted canonical event chain. | 6 |
| C | Wrong effective date. | 0 |
| D | Wrong known-at/publication date. | 0 |
| E | Conflicting authoritative sources. | 0 |
| F | Duplicate event. | 0 |
| G | Parser/extraction defect. | 0 |
| H | Historical symbol/name change or corporate-action transition; dated first-party identity evidence exists but no durable-ID certification is claimed. | 31 |
| I | Corporate action requiring explicit instrument lineage. | 0 |
| J | Durable-ID gap or ambiguous identity. | 0 |
| K | Checkpoint count/source defect. | 0 |
| L | Checkpoint date/calendar defect. | 0 |
| M | Unexpected synthetic or reconstructed event. | 0 |
| N | Source tier/authority insufficiency. | 0 |
| O | Unresolved evidence gap. | 0 |

Primary assignment is one category per CSV row. `H=31` covers dated symbol/name transition patterns including the NAM-INDIA spelling, the PIPAVAVDOC/RDEL pair, and the CADILAHC/ZYDUSLIFE transition. `A=6` covers the six symbols appearing only in the later 2021-09-30 roster; `B=6` covers the six symbols appearing only in the earlier 2021-08-31 roster. Categories C-G and I-O have zero primary assignments in these 43 rows; their blockers remain relevant to the overall contract.

### Symbol-level findings

- Transition groups with same-instrument evidence: MADRASCEM/RAMCOCEM; SESAGOA/SSLT/VEDL; UNIPHOS/UPL; INFOTECENT/CYIENT; PIPAVAVDOC/RDEL; SKSMICRO/BHARATFIN; IDFCBANK/IDFCFIRSTB; RNAM/NAM-INDIA; TATAGLOBAL/TATACONSUM; NIITTECH/COFORGE; IBVENTURES/DHANI; INFRATEL/INDUSTOWER; ADANIGAS/ATGL. These are diagnostic identity links, not permission to rewrite the event chain.
- CADILAHC/ZYDUSLIFE is a dated symbol/name transition candidate. The historical master contains INE010B01019 and later INE010B01027 evidence; NSE symbol-change/name-change files are present but marked manual review. It therefore remains category H and unresolved for durable-ID certification.
- The 2021-09-30 six-for-six group is not a symbol alias group. The A1 September roster itself proves the later endpoint members. The existing A1 `ind_prs15092021.pdf` press release (SHA-256 `56ab5fbf0a9e6e934ba0c4f1bc89444455e808a7b041ad58cab64ae52e9084db`) corroborates five of the six substitutions in its NIFTY Midcap 150 section (BBTC, CESC, GODREJAGRO, IBULHSGFIN, VGUARD excluded; HINDCOPPER, INDIANB, IRFC, NATIONALUM included), but it is not a NIFTY-200 event record and does not mention ASTRAL or TATACOMM. No canonical event correction is therefore justified.
- `NAMINDIA` in the reconciliation is the normalized spelling of the source roster symbol `NAM-INDIA`; the endpoint source is not being edited.

## 3. Evidence and source treatment

- The 16 later checkpoint sources are first-party A1 NIFTY-200 monthly roster PDFs in the existing source catalogue. Full earlier/later URLs and SHA-256 values are in the CSV; no new source bytes were admitted.
- Dated NSE bhavcopy identity evidence is used only diagnostically for the H rows. The identity-resolution notes explicitly warn that current listing evidence alone is not historical anchor evidence.
- Existing canonical event sources and hashes surrounding each instrument are retained in the CSV as `canonical_event_source_evidence`; no event was added, removed, or rewritten.
- The 2016-04-29, 2016-07-29, 2018-12-31, 2019-01-31, 2019-12-31, 2020-01-31, and 2020-02-28 endpoints contain 201 parsed unique members and remain manual-review checkpoints. The 2016-04-29 interval has a derived replay count of 202 because the later roster is 201 and RDEL is an additional symbol diagnostic; this was not normalized away.

## 4. ABBOTINDIA and OFSS

- ABBOTINDIA 2022-03-31 ADD remains an unresolved duplicate-event conflict: the earlier canonical ADD is 2020-06-26 and the later DROP is 2023-09-29. Existing source `https://www.niftyindices.com/Press_Release/ind_prs24022022_1.pdf`, SHA-256 `3091cf1c10b57bbae3b81645f5d91916a1af2bb7284902060f4640f7fb9fcd56`, remains raw and `UNRESOLVED_MANUAL_REVIEW`.
- OFSS 2024-03-28 ADD remains an unresolved duplicate-event conflict: an earlier DROP is 2021-03-31 and ADD is 2022-03-31. Existing source `https://www.niftyindices.com/Press_Release/ind_prs28022024.pdf`, SHA-256 `5c70d043edde682a31fc5fa043a3b829a380fc9896de904bcb76d64b8319f698`, remains raw and `UNRESOLVED_MANUAL_REVIEW`.
- Neither conflict was used to explain or repair any of the 16 intervals.

## 5. Durable-ID, replay, and readiness result

- Durable-ID completeness: all 107 interval rows remain identity-incomplete; exact durable-ID set equality is not certifiable for all 107. Current validation reports 45.7902% ISIN resolution among historical event rows, with the existing unresolved identity/durable-ID review blockers unchanged.
- Event-sourced replay: not rerun because this forensic pass made no admissible source, canonical-event, identity, or software correction. The measured result is unchanged: 107 intervals, 91 diagnostic symbol matches, 16 diagnostic divergences, 43 divergence occurrences, and no certifiable exact-set result.
- Anchor/calendar: unchanged at `anchor_status=NOT_ESTABLISHED` and `calendar_audit_status=PARTIAL_NOT_CERTIFIED`; the artifact has 68 missing or non-200 checkpoints and 58 valid-200 checkpoints.
- Import/dry-run: no new run was executed. The retained artifact result is `REFUSED_AS_DESIGNED`, `database_touched=false`, because manifest validation was not PASS.
- No Stage A, research, backtest, paper/live trading, broker/API call, production DuckDB/WAL access, push, or merge occurred.

## 6. Verification and disposition

- Verified the authoritative worktree identity and preserved its pre-existing modified/untracked reports.
- Verified the 16-row/43-occurrence reconciliation directly from the current artifact; the CSV contains one row per occurrence and 41 unique normalized symbols.
- No logical correction group was authorized by evidence, so there is no before/after corpus delta to replay. The report-only commit is the only intended change.
- Final disposition: `EVENT_SOURCED_CONTRACT_NOT_READY`.

## 7. Detailed records

See `nifty200_pit_divergent_interval_forensics_20260922.csv` for all 43 rows, including endpoint source URLs/hashes, identity evidence, canonical event context, raw observations in each interval, expected action, root category, and blocking notes.
