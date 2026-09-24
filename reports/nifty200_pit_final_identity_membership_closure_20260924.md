# NIFTY-200 final durable-identity and prior-membership closure

Audit date: 2026-09-24. Worktree: `C:\Python projects\algo trading-authoritative-evidence`. Branch: `codex/nifty200-pit-authoritative-evidence`.

Starting HEAD: `c32989b57035f0ea2679fa92e7fd51cad3f0828e`. The pass was report-only. Existing dirty and untracked work was preserved.

## Decision

`SUFFIX_MEMBERSHIP_REPLAY_BLOCKED`

The separated suffix replay is unchanged at 68/74 certification-grade exact intervals, six economic divergences, and 26 representation-only intervals. Both membership-affecting evidence gaps remain unresolved. No unsafe identity inference was used.

## 1. Starting evidence gaps

The current conflict CSV contains exactly two `UNRESOLVED_EVIDENCE_GAP` rows:

| Gap | Conflict | Security | Durable ID | Conflict/effective date | Canonical event | Raw observation | Source | Exact missing proof |
|---|---|---|---|---|---|---|---|---|
| YESBANK identity continuity | `6dcacbb919dcc057913cfdfcfafd680e756b6fc153d8977fbfbe9d4b9208c6e3` | YESBANK | `NSE-ISIN:INE528G01035` | 2020-03-19 | accepted `DROP`, event `713bfae9fba9ebac12fa8cf13c34fc8b79bc640862683570144e1bda25ed6d54` | `561155c32acdcaa9d058273387329ce7cdd34e83f5338335d1f2395646dd05b6` | `ind_prs16032020.pdf`, page 3, SHA-256 `4e7726fa8bfe5dc12f2b42121f69fd29bc7ec1da01c2c26dae84f2f3fe8e9f37` | period-valid first-party continuity linking checkpoint IDs `INE528G01027`/the carried `INE528G01019` namespace to acted-on ID `INE528G01035`; the later August ADD is not prior-state proof |
| GRASIM prior membership | `d367a47231c8653470c19daf432b35b6b280fd6c7c9a395d3741ea1ce533f46a` | GRASIM | `NSE-ISIN:INE047A01021` | 2017-05-26 | accepted `DROP`, event `ceb006fc816c3ddfee0e419fa0067be0d5da7f20a5657937bc69eb49820a51c8` | `cae375c2ecd2ec6d9692a13ace0910ed0d56b04a89b9cd493b7187710b0fb0485` | `ind_prs27042017.pdf`, page 4, SHA-256 `a72ac75b320579a3bf981b43466d9569caf2dfce94d00b584d750498e110347b` | authoritative prior NIFTY-200 ADD or equivalent membership history for exact ID `INE047A01021`; later presence is not backdated |

## 2. YESBANK namespace trace

| Point | Checkpoint identity | Raw/canonical event identity | Interval/alias result |
|---|---|---|---|
| 2020-02-28 checkpoint | ledger row `53103088112bddf1478fee74b60b4604be3a4b971ca57200619327ee0a047bcb`; symbol `YESBANK`; ISIN `INE528G01027`; durable `NSE-ISIN:INE528G01027`; `CERTIFIED_UNIQUE` dated bhavcopy identity | none | checkpoint economic state contains the 027 namespace |
| 2020-03-19 DROP | no checkpoint on the effective date | raw symbol `YESBANK`, ISIN `INE528G01035`, canonical `NSE-ISIN:INE528G01035`; accepted A1 event `713bfa...`; observation `561155...`; known at `2020-03-17T09:15:00+05:30` | carried strict raw replay still has `NSE-ISIN:INE528G01019`; target 035 is absent, so the transition is `ABSENT -> DROP` for the target and the old carried ID remains |
| 2020-03-31 checkpoint | no YESBANK member row in the checkpoint ledger | the March DROP remains the only accepted NIFTY-200 YESBANK transition in this interval | the six economic divergences begin with 2020-02-28 -> 2020-03-31 |
| 2020-08-31 evidence | dated bhavcopy identity maps `YESBANK` to `INE528G01035`, SHA-256 `8140b9f8cea524172bf603fa274ba8a5f21b91584c54a2c0eb4dfa975f805204`; this is identity evidence, not a membership assertion | no NIFTY-200 ADD before September | does not prove the prior membership state needed for the March DROP |
| 2020-09-25 ADD | no checkpoint on the effective date | raw symbol `YESBANK`, ISIN `INE528G01035`, canonical `NSE-ISIN:INE528G01035`; accepted A1 event `391328cc82b38f20fe051c73c0ae9a01c45bc0e1c61009bfeb7c8093408c6eb9`; observation `2916788de5dff6a62bdf02156df17a7798b015eef2632dbf389acdeb1e69c161`; known at `2020-08-21T09:15:00+05:30` | valid later ADD for ID 035; it does not establish prior continuity |
| first checkpoint after ADD | 2020-09-30 ledger row `9f3b3a5978a8c05db8a00bb40c3c71faca4f0c5dc7f47de62520bebfd5109097`; symbol `YESBANK`; ISIN/durable ID `INE528G01035`; `CERTIFIED_UNIQUE` | matches September canonical ID 035 | constituent interval `d1c8d9b0e15d40bd0224b218b29b26b986bb21ce7c9b86ad3cf83ea0a964ff15`, effective from 2020-09-25, entry event `391328...` |

The local `historical_instrument_master.parquet` contains period-valid dated rows for the 027 namespace through 2020-02-28 and the 035 namespace beginning 2020-03-19. The local `instrument_aliases.parquet` does not contain an admitted 027-to-035 continuity edge, and `identity_continuity_evidence.json` contains eight unrelated stock-split links but no YESBANK link. Thus the local material is `IDENTITY_NAMESPACE_MAPPING_GAP`, not evidence already consumed by the replay layer.

The same trace also shows the carried suffix seed identity `NSE-ISIN:INE528G01019`. No period-valid authoritative edge joining `019 -> 027 -> 035` is present in the accepted continuity evidence. The mismatch is therefore an evidence/namespace continuity gap, not a proven production replay defect.

The event corpus also contains an official workbook date-only YESBANK DROP observation and a B1 candidate for the March 2020 DROP. Neither has been admitted as a replacement for the accepted A1 PDF event. The August A1 PDF ADD remains the sole accepted later NIFTY-200 ADD for ID 035.

## 3. YESBANK dated local first-party identity evidence

All matching A1 `DATED_BHAVCOPY_IDENTITY` rows in the audited local corpus for 2019-12-01 through 2020-10-01 are listed below. Each has an explicit historical validity interval and is identity evidence only.

| Observation date | ISIN | Source SHA-256 |
|---|---|---|
| 2019-12-27 | `INE528G01027` | `bfff98fd90e3d1eeb87c61a1f2145850c95c36943a63328b0d08ba95fcfa6fad` |
| 2019-12-31 | `INE528G01027` | `2eee01afd56a8afc38c90b550155089ce64ae42973210c496c0405d7fe620a4b` |
| 2020-01-31 | `INE528G01027` | `13c2069e482a6e90b789c5de61415c1b389bd2ac543a941ffa7fb1e06d103439` |
| 2020-02-28 | `INE528G01027` | `2c5b8348dec6e64e0064bb8a77abe5811a2cc4eb1f720ac001ff923d6ae86b33` |
| 2020-03-19 | `INE528G01035` | `9c590311f613e0c1f33d07ab52a3ba4426bd867ac3a258f7dce38748d6db55b7` |
| 2020-03-27 | `INE528G01035` | `f68e1c9c7b4d935282508238eca0c9b171691994640acdec2505513998d86385` |
| 2020-03-31 | `INE528G01035` | `4c0db14d6cf4fe218dff20074d086886d93ba85a8c3ad803412fb1275a8b891b` |
| 2020-04-30 | `INE528G01035` | `eb52be9f2bf529e5a5019fab90ebee4da8b3e9adac6e5ab6fb3fa5b088110814` |
| 2020-05-29 | `INE528G01035` | `3a0b1a004796e9466237122ef7cd7f492849250049a5a67e78ca2f2e515aecbb` |
| 2020-06-26 | `INE528G01035` | `c4c1f555bc63ccffc102e3d265ac77edcea2d15e87feae995429e9d2613f19eb` |
| 2020-06-30 | `INE528G01035` | `d6a645a82bbd70903edbffaf541809682d9268d73548de5fcacdea70c7c0858a` |
| 2020-07-31 | `INE528G01035` | `26cbb9286efe0123d66c0e988f90107e32b6f3ea8a2e63701ec97d73a20dd306` |
| 2020-08-31 | `INE528G01035` | `8140b9f8cea524172bf603fa274ba8a5f21b91584c54a2c0eb4dfa975f805204` |
| 2020-09-25 | `INE528G01035` | `579148b2c647823c4b6681d55c93ac6042f0982e39fe067c3d7eb23a17eac2f9` |
| 2020-09-30 | `INE528G01035` | `704313e2d8578e815d9f069e73e4e9a8a655f583dec0dd52e643132ef3d65c42` |

## 4. Targeted YESBANK first-party search

The local corpus was insufficient, so a narrow first-party search was performed. No new source was admitted because the raw bytes and a verified SHA-256 were not available for registration in the authoritative corpus.

| Candidate | Assertion | SHA-256 | Disposition |
|---|---|---|---|
| [NSE Circular INSP43833](https://nsearchives.nseindia.com/content/circulars/INSP43833.pdf), dated 2020-03-15 | identifies YESBANK and the new ISIN `INE528G01035` from 2020-03-16, but does not explicitly name old ISIN `INE528G01027` | not present in this local closure corpus | not admitted; insufficient by itself for the old-to-new edge |
| [NSDL Circular 2020-0033](https://nsdl.co.in/downloadables/pdf/2020-0033-Policy-Yes%20Bank%20Limited%20Reconstruction%20Scheme%2C%202020.pdf), dated 2020-03-17 | explicitly states YESBANK old ISIN `INE528G01027` and new ISIN `INE528G01035`, with the corporate-action relationship | not computed; official bytes could not be retrieved for preservation and hash validation | rejected for this pass; candidate is the smallest exact YESBANK target for the next evidence pass |
| [BSE FY2019-20 annual report](https://www.bseindia.com/bseplus/AnnualReport/532648/5326480320.pdf) | states new ISIN `INE528G01035` and old ISIN `INE528G01027` | not computed; raw bytes not preserved | rejected for PIT known-at continuity because it is a later annual report, not a period-near event notice |

Accordingly:

`YESBANK_DURABLE_IDENTITY_CONTINUITY_NOT_PROVEN`

The exact proof chain remains incomplete. The dated NSDL circular is a promising candidate, but using search-result text without preserved bytes, source hash, retrieval metadata, and pipeline registration would violate the evidence boundary.

## 5. GRASIM state trace

The target is only `NSE-ISIN:INE047A01021`.

| Point | State/evidence |
|---|---|
| suffix seed, 2016-01-29 | checkpoint member `GRASIM` is `NSE-ISIN:INE047A01013`; exact target 021 is absent |
| last proven absent exact target | 2016-09-30 checkpoint still has `GRASIM` as ID 013; exact ID 021 is absent |
| first proven present exact target | 2016-10-30 checkpoint has `GRASIM`, ISIN/durable ID `INE047A01021`; local dated identity evidence also exists on 2016-10-24 and 2016-10-30 |
| immediately before DROP | 2017-04-28 checkpoint has exact target 021 present |
| unresolved DROP | publication 2017-04-27; known at `2017-04-28T09:15:00+05:30`; effective 2017-05-26; accepted NIFTY-200 page 4 DROP |
| after DROP | 2017-05-31 checkpoint has no GRASIM member row |
| later accepted ADD | publication 2018-02-21; known at `2018-02-22T09:15:00+05:30`; effective 2018-04-02; event `82a4011625116dc115aeeadff3076991bf0cf14744444ab46cc1f62220852d67`; source SHA-256 `a31019896822ef7a28f2229ba5e1552c835f51952ee033d02a5f79c9c7914b3d` |

The exact prior-ADD window derived from the checkpoint ledger is:

`after 2016-09-30 and on/before 2016-10-30`

The local 2016-10-24/30 dated bhavcopies prove the identity `GRASIM -> INE047A01021`, but do not assert NIFTY-200 membership. The existing 2018 ADD is after the 2017 DROP and cannot be backdated. The state-machine classification is `MISSING_PRIOR_ADD`, with an underlying 013-to-021 identity/alias continuity gap; the evidence does not justify manufacturing an ADD.

All existing raw/canonical observations for the exact target are:

| Observation ID | Tier/status | Action/effective date | Source |
|---|---|---|---|
| `682811271d169b24d4e9e073d5490a3110ad6e1807e57e9a5a920b018cc4528a` | B1 / unresolved | DROP / 2017-05-26 | `https://raw.githubusercontent.com/deshpanda/nse-screener-data/main/reconstitution/events.parquet`, SHA-256 `2abc0e22e14305c83ed38d50f003c3b20a71f13555f0c8918d092c462598cb53` |
| `cae375c2ecd2ec6d9692a13ace0910ed0d56b04a89b9cd493b7187710bfb0485` | A1 / accepted | DROP / 2017-05-26 | `ind_prs27042017.pdf`, SHA-256 `a72ac75b320579a3bf981b43466d9569caf2dfce94d00b584d750498e110347b` |
| `e4956e9c6e8ebff34fbc8fae229f0fca0345b20a4f9d14bc6761d42e64906d23` | A1 / manual review | DROP / 2017-05-26 | `https://archives.nseindia.com/content/indices/IndexInclExcl.xls`, SHA-256 `8869bb7c4df67403131a494a8cc65509e80828f9438bc150b506cdbf55378046` |
| `5303cb5b5637726a9b157182663b4bcbbb22d2dd398d880d8429fb9ec3668b28` | B1 / unresolved | ADD / 2018-04-02 | `https://raw.githubusercontent.com/deshpanda/nse-screener-data/main/reconstitution/events.parquet`, SHA-256 `2abc0e22e14305c83ed38d50f003c3b20a71f13555f0c8918d092c462598cb53` |
| `29341ae568c6980c0956cbc21524ab9fbb9fa61ef5fc78a55d72a1a9eaf38a56` | A1 / accepted | ADD / 2018-04-02 | `ind_prs21022018.pdf`, SHA-256 `a31019896822ef7a28f2229ba5e1552c835f51952ee033d02a5f79c9c7914b3d` |
| `894a4eccd1ac0e07843a28a1a586e10075658d62a00e1dca1a56f2aa9dc6670d` | A1 / manual review | ADD / 2018-04-02 | `https://archives.nseindia.com/content/indices/IndexInclExcl.xls`, SHA-256 `8869bb7c4df67403131a494a8cc65509e80828f9438bc150b506cdbf55378046` |

## 6. Targeted GRASIM first-party search

The following narrow official NSE Indices sources were checked against the derived window and the required NIFTY-200 section:

| Source | Finding | SHA-256/admission |
|---|---|---|
| [NSE Indices release 17-Oct-2016](https://www.niftyindices.com/Press_Release/ind_prs17102016.pdf) | NIFTY 200 changes concern Cairn/Vedanta effective 2016-11-15; no GRASIM ADD | local accepted events hash `e3ad170876e6278ad7a1e99cc924ba610c3f8be4ef0dc85cd2c146e2152ca4ea`; no GRASIM ADD admitted |
| [NSE Indices broad-market structure release 22-Feb-2016](https://www.niftyindices.com/docs/default-source/press-release-upload/ind_prs22022016_1.pdf) | describes the NIFTY 200 structure effective 2016-04-01, not an exact prior membership event in the derived window | no new source admitted; outside the exact window |
| [NSE Indices release 18-Jul-2016](https://www.niftyindices.com/docs/default-source/press-release-upload/ind_prs18072016.pdf) | GRASIM appears in Nifty Alpha 50, not NIFTY 200 | rejected; wrong index section |
| [NSE Indices release 07-Jan-2016](https://www.niftyindices.com/Press_Release/ind_prs07012016.pdf) | GRASIM appears in the Nifty Aditya Birla Group action, not NIFTY 200 | rejected; wrong index section and outside the exact window |
| local `ind_prs21022018.pdf` canonical ADD | exact NIFTY-200 ADD for ID 021 effective 2018-04-02 | admitted existing evidence, but too late to close the 2017 prior-state requirement |

`GRASIM prior ADD proven = NO`.

## 7. Replay and conflict accounting

No source, canonical event, identity artifact, replay output, or production code was changed.

| Metric | Before | After |
|---|---:|---:|
| Checkpoints | 75 | 75 |
| Intervals | 74 | 74 |
| Checkpoint identity rows | 15,050 / 15,050 | 15,050 / 15,050 |
| Certification-grade exact | 68 / 74 | 68 / 74 |
| Economic divergences | 6 / 74 | 6 / 74 |
| Representation-only intervals | 26 | 26 |
| Unresolved evidence-gap conflicts | 2 | 2 |
| Membership-affecting unresolved conflicts | 2 | 2 |

The six YESBANK intervals remain `STILL_DIVERGENT`:

1. 2020-02-28 -> 2020-03-31
2. 2020-03-31 -> 2020-04-30
3. 2020-04-30 -> 2020-05-29
4. 2020-05-29 -> 2020-06-30
5. 2020-06-30 -> 2020-07-31
6. 2020-07-31 -> 2020-08-31

The YESBANK conflict is `STILL_UNRESOLVED` because the only newly found exact old-to-new source was not admitted with preserved bytes and a verified hash. The GRASIM conflict is `STILL_UNRESOLVED` because no prior NIFTY-200 ADD or equivalent exact membership-history assertion was found in the derived window. No production PIT defect was found.

## 8. Verification and boundaries

- Arithmetic and deterministic rerun checks reproduced 75 checkpoints, 74 intervals, 68 exact, 6 economic divergences, and 26 representation-only intervals.
- CSV uniqueness checks passed for the new closure CSV and the current conflict identifiers; the closure CSV has one row per `record_id`.
- Referenced accepted source hashes were checked against the current canonical-event and historical-identity artifacts.
- `git diff --check` was run after report creation.
- No calendar certification, 2015-12-31 frontier, pre-2016 general acquisition, post-2022 work, 2012 anchor, governance change, Stage A, research, backtests, paper/live trading, broker call, production DuckDB/WAL access, push, or merge occurred.

Global governance remains unchanged:

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

Smallest next evidence targets only:

1. Preserve and register the dated official NSDL YESBANK circular proving `INE528G01027 -> INE528G01035`, including raw bytes, retrieval timestamp, SHA-256, known-at, and pipeline linkage.
2. Locate one official NIFTY-200 membership/ADD assertion after 2016-09-30 and on/before 2016-10-30 for `GRASIM` / `INE047A01021`, or an equally authoritative event-history record that explicitly closes the 013-to-021 membership continuity.

No broad research is recommended.
