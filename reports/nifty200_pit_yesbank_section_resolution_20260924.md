# NIFTY-200 YESBANK source-section and state-machine closure

Audit date: 2026-09-24. Worktree: `C:\Python projects\algo trading-authoritative-evidence`. Branch: `codex/nifty200-pit-authoritative-evidence`. Starting and ending HEAD for this report-only pass: `e36010440043e8675678f8e30904f7e69e47104b`.

Scope is limited to the six remaining YESBANK economic divergences, the applicable YESBANK conflict, and the three named first-party releases. Calendar certification, the 2015 frontier, the 2012 anchor, post-2022 data, general identity acquisition, governance, Stage A, research, trading, broker integration, production DuckDB, and WAL were untouched.

## Decision summary

- `MARCH2020_DROP_PROVEN`: YES. The March 16, 2020 release states removal from all NIFTY equity indices effective March 19, 2020, and page 3 explicitly lists YESBANK under `7) NIFTY 200` as excluded.
- `SEPT2020_NIFTY200_ADD_PROVEN`: YES. The August 20, 2020 release page 14, section `m) NIFTY 200`, lists Yes Bank Ltd. / YESBANK among the companies being included effective September 25, 2020.
- `YESBANK_2022_NIFTY200_DROP_NOT_EXPLICIT`: YES. The February 24, 2022 release has YESBANK actions in NIFTY Next 50, NIFTY 100, NIFTY Midcap 150, NIFTY Midcap 100, and NIFTY MidSmallcap 400, but not in the NIFTY 200 section. The NIFTY 200 section spans pages 14–15 and does not list YESBANK.
- `PRODUCTION_PIT_DEFECT_FOUND = NO`.
- Final decision remains `SUFFIX_MEMBERSHIP_REPLAY_BLOCKED`.

The official releases are [March 16, 2020](https://www.niftyindices.com/Press_Release/ind_prs16032020.pdf), [August 20, 2020](https://www.niftyindices.com/Press_Release/ind_prs20082020.pdf), and [February 24, 2022](https://www.niftyindices.com/Press_Release/ind_prs24022022_1.pdf).

## Source verification

| Source | Local SHA-256 | Section and page | Finding |
|---|---|---|---|
| `ind_prs16032020.pdf` | `4e7726fa8bfe5dc12f2b42121f69fd29bc7ec1da01c2c26dae84f2f3fe8e9f37` | Page 1 general rule; page 3, `7) NIFTY 200` | Explicit YESBANK DROP, effective 2020-03-19, close 2020-03-18 |
| `ind_prs20082020.pdf` | `46c98f2c6cc53f925bed74bface526afc752a39706828836be23ab38d1fa898c` | Page 14, `m) NIFTY 200`, included table row 8 | Explicit YESBANK ADD, effective 2020-09-25, close 2020-09-24 |
| `ind_prs24022022_1.pdf` | `3091cf1c10b57bbae3b81645f5d91916a1af2bb7284902060f4640f7fb9fcd56` | Pages 14–15, `12) NIFTY 200` | No YESBANK DROP or ADD in the NIFTY 200 section |

All three source bytes are already in the source catalogue as downloaded A1 evidence. The August source is already represented in the raw observations, canonical events, and `constituent_intervals.parquet`; no evidence registration or derived-event edit was required.

## Current canonical YESBANK timeline

The current NIFTY-200 canonical timeline contains exactly two accepted PDF-derived events:

| Raw observation ID | Canonical event ID | Source section | Action | Publication | Known at | Effective | Durable ID |
|---|---|---|---|---|---|---|---|
| `561155c32acdcaa9d058273387329ce7cdd34e83f5338335d1f2395646dd05b6` | `713bfae9fba9ebac12fa8cf13c34fc8b79bc640862683570144e1bda25ed6d54` | `ind_prs16032020.pdf`, page 3, `7) NIFTY 200` | DROP | 2020-03-16 | 2020-03-17 09:15 IST | 2020-03-19 | `NSE-ISIN:INE528G01035` |
| `2916788de5dff6a62bdf02156df17a7798b015eef2632dbf389acdeb1e69c161` | `391328cc82b38f20fe051c73c0ae9a01c45bc0e1c61009bfeb7c8093408c6eb9` | `ind_prs20082020.pdf`, page 14, `m) NIFTY 200` | ADD | 2020-08-20 | 2020-08-21 09:15 IST | 2020-09-25 | `NSE-ISIN:INE528G01035` |

The raw event observations also contain an official workbook date-only YESBANK DROP and a B1 candidate for March 2020. Neither replaces the accepted A1 PDF event; no duplicate event was created.

## Section-scoping audit

The February 2022 source was inspected by section, not by global YESBANK text matching:

| Index section | YESBANK action in source | Relevant pages |
|---|---|---:|
| NIFTY Next 50 | DROP | 2 |
| NIFTY 100 | DROP | 5 |
| NIFTY Midcap 150 | ADD | 6 |
| NIFTY Midcap 100 | ADD | 11 |
| NIFTY 200 | NONE | 14–15 |
| NIFTY MidSmallcap 400 | ADD | 18, continuation of that section |

The parser/canonicalizer retains `index_id=NIFTY_200`, `source_index_name=NIFTY 200`, and source pages for the two canonical events. The February YESBANK rows in other index sections did not become NIFTY-200 events. No global company-name propagation, wrong-section association, or cross-index contamination was found. No focused parser fix or regression was warranted.

## State machine

Before March 2020, economic YESBANK membership is present. The strict carried raw replay seed contains `NSE-ISIN:INE528G01019`; the 2020-02-28 certified checkpoint identifies YESBANK as `NSE-ISIN:INE528G01027`. The later event identity is `NSE-ISIN:INE528G01035`. The current evidence proves each dated identity separately but does not prove the temporal continuity `019 → 027 → 035` as one durable economic identity.

The event sequence is therefore:

1. Economic state PRESENT before 2020-03-19.
2. The authoritative NIFTY-200 DROP is proven for 2020-03-19, but its canonical ID `035` is absent from the carried raw replay state, which still contains `019`; raw replay records `ABSENT → DROP` and leaves the old ID active.
3. Economic state is intended to be ABSENT after the proven DROP, but certification-grade raw-ID equality cannot be asserted without the missing continuity evidence.
4. The authoritative NIFTY-200 ADD is proven for 2020-09-25 and is already canonicalized as `035`; it is a valid later `ABSENT → ADD` for that ID and creates the stored YESBANK constituent interval from 2020-09-25 onward.
5. February 2022 provides no NIFTY-200 YESBANK action, so no later YESBANK state transition is added through the suffix endpoint 2022-03-31.

The August ADD is after the March DROP. It proves the later NIFTY-200 inclusion but does not prove a prior ADD for the March DROP target, and therefore does not close the YESBANK `ABSENT → DROP` conflict.

## Six remaining intervals

The six rows were extracted directly from the current forensic CSV; no dates were reconstructed manually.

| Interval | Raw replay YESBANK ID | Checkpoint identity context | Classification | Causal role |
|---|---|---|---|---|
| 2020-02-28 → 2020-03-31 | `INE528G01019` | Previous checkpoint `INE528G01027`; next checkpoint has no YESBANK row | `REMAINS_EVIDENCE_GAP` | First causal divergence; YESBANK conflict `6dcac...` |
| 2020-03-31 → 2020-04-30 | `INE528G01019` | No endpoint YESBANK row | `REMAINS_EVIDENCE_GAP` | Propagated |
| 2020-04-30 → 2020-05-29 | `INE528G01019` | No endpoint YESBANK row | `REMAINS_EVIDENCE_GAP` | Propagated |
| 2020-05-29 → 2020-06-30 | `INE528G01019` | No endpoint YESBANK row | `REMAINS_EVIDENCE_GAP` | Propagated |
| 2020-06-30 → 2020-07-31 | `INE528G01019` | No endpoint YESBANK row | `REMAINS_EVIDENCE_GAP` | Propagated; associated VEDL conflict has no YESBANK consequence |
| 2020-07-31 → 2020-08-31 | `INE528G01019` | No endpoint YESBANK row | `REMAINS_EVIDENCE_GAP` | Propagated |

No interval is resolved by the September ADD because all six end before 2020-09-25. No interval is a calendar or effective-date error; the March effective date is explicit and correctly canonicalized.

## Two unresolved conflicts

- YESBANK, 2020-03-19, conflict `6dcacbb919dcc057913cfdfcfafd680e756b6fc153d8977fbfbe9d4b9208c6e3`: the March DROP is proven and section-correct, but a prior authoritative identity-continuity/ADD record is still required to connect the carried `019`/checkpoint `027` state to event ID `035`. The August 2020 ADD does not close this prior-state gap because it occurs later.
- GRASIM, 2017-05-26, conflict `d367a47231c8653470c19daf432b35b6b280fd6c7c9a395d3741ea1ce533f46a`: unrelated to YESBANK. Its smallest remaining requirement is a first-party prior ADD or equivalent authoritative event-history evidence for `NSE-ISIN:INE047A01021`; this task does not broaden into that research.

## Replay and verification

No source, canonical event, parser, or derived artifact was changed. Consequently the separated replay remains:

- `CERTIFICATION_GRADE_EXACT = 68 / 74` separated accounting;
- `ECONOMIC_DIVERGENT = 6 / 74`;
- `REPRESENTATION_ONLY = 26`;
- unresolved evidence-gap conflicts remain `2`.

Fresh checks confirmed the three PDF SHA-256 values, two canonical YESBANK events, the August event's presence in `constituent_intervals.parquet`, six unique divergent intervals, and the two unresolved conflicts. The temporary audit probes were removed. `git diff --check` is clean for tracked changes. This was report-only, so PIT/full pytest, Ruff, Mypy, Pyright, and compileall were not rerun.

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
