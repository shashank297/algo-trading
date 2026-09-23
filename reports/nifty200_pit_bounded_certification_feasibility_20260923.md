# NIFTY-200 PIT bounded certification feasibility audit

Date: 2026-09-23
Repository: `shashank297/algo-trading`
Worktree: `C:\\Python projects\\algo trading-authoritative-evidence`
Branch: `codex/nifty200-pit-authoritative-evidence`
Starting HEAD: `1378eaee651d1888e60c3edf6a6bc93b8ea2a1af`
Scope: report-only bounded feasibility audit under the current strict PIT rules.

## 1. Result

`BOUNDED_PIT_CERTIFICATION_BLOCKED`

The strongest bounded historical period is not currently certifiable under the existing strict rules. The bounded evidence has useful passing components—complete source files, valid hashes, source-supported 201-member DVR states, canonical event-field completeness, and 107/107 durable-ID replay—but the following current-rule gates remain blocking:

1. checkpoint roster rows have no durable IDs: 0/21,650 raw roster rows are durable-ID certified; 4,356 are ambiguous under diagnostic symbol mapping;
2. 268 bounded raw event observations remain non-canonicalized, including 267 B1 observations and one unresolved A1 IBULHSGFIN observation;
3. 74 bounded CRITICAL `REMOVAL_OF_ABSENT_MEMBER` conflicts remain unresolved;
4. the bounded calendar is entirely package-only: 0 authoritative-covered dates out of 3,270 audited dates;
5. two canonical events effective on 2020-07-31 cannot be mapped to a package session with certified calendar evidence;
6. the current validator accepts date parameters but the current artifact/build path is global-scope and is not a clean bounded-package workflow;
7. independent PIT/data QA is not asserted.

No governance rule, campaign start date, validator semantic, source catalogue, importer, or software implementation was changed.

## 2. Repository state

- Worktree: `C:\Python projects\algo trading-authoritative-evidence`
- Branch: `codex/nifty200-pit-authoritative-evidence`
- Starting HEAD: `1378eaee651d1888e60c3edf6a6bc93b8ea2a1af`
- `origin/main`: `635acfcf62596c0c145f4032dde1e7020407e98e`
- Local commits since `origin/main`: 10
- Existing modified reports preserved:
  - `reports/nifty200_pit_2012_anchor_forensics_20260911.md`
  - `reports/nifty200_pit_initial_anchor_20120102.md`
- Existing untracked reports preserved:
  - `reports/nifty200_pit_authoritative_closure_20260921.md`
  - `reports/nifty200_pit_authoritative_evidence_gap_report_20260920.md`
  - `reports/nifty200_pit_authoritative_phase_baseline_20260920.md`
  - `reports/nifty200_pit_certification_governance_options_20260921.md`
  - `reports/nifty200_pit_exact_date_identity_linkage_20260921.md`
  - `reports/nifty200_pit_monthly_checkpoint_classification_20260921.md`
- Existing `.pytest-tmp*` permission warnings/untracked directories were not touched.

## 3. Bounded period and checkpoint coverage

Candidate period:

- start: 2013-04-18
- end: 2022-03-31
- excluded: 2012 and post-2022, except where a boundary fact is necessary to explain a bounded blocker

Current artifacts verify:

| Requirement | Result |
| --- | --- |
| authoritative start checkpoint | present as 200-row A1 source |
| authoritative end checkpoint | present as 200-row A1 source |
| authoritative checkpoint dates | 108 |
| adjacent replay intervals | 107 |
| source authority | 108/108 A1 |
| checkpoint source hashes | 108/108 valid |
| snapshot rows | 21,650 |
| 200-row checkpoints | 58 |
| source-supported 201-row checkpoints | 50 |
| missing checkpoint dates in bounded span | 0 |

Start source:

- URL: `indices_dataApr2013.zip`
- source member: `cnx200_Apr2013.csv`
- SHA-256: `4942c0f021abcd6ed9702c343c2696ec44cfa8022c7e37448f8a78c075c4a16d`
- 200 parsed rows, 200 unique symbols
- diagnostic identity: 164 exact period-valid symbol matches, 36 ambiguous, 0 unmatched

End source:

- URL: `indices_dataMar2022.zip`
- source member: `NIFTY_200_Mar2022.pdf`
- SHA-256: `44a182c845eac8ddd6864abe535d02c6ce9bdecc0adbf11a16e25133cc44b969`
- 200 parsed rows, 200 unique symbols
- diagnostic identity: 154 exact period-valid symbol matches, 46 ambiguous, 0 unmatched

## 4. Starting and ending checkpoint certification

### Start: `START_CHECKPOINT_BLOCKED`

The 2013-04-18 source is complete, first-party A1, byte-preserved, hash-valid, independently separate from event sources, and has a source-supported 200-row count. It is not certifiable as a strict PIT starting state because the roster has no durable identifiers. The diagnostic mapping leaves 36 of 200 rows ambiguous; the remaining 164 symbol matches are not a substitute for durable source identity.

### End: `END_CHECKPOINT_BLOCKED`

The 2022-03-31 source is complete, first-party A1, byte-preserved, hash-valid, independently separate from event sources, and has a source-supported 200-row count. It is not certifiable as a strict PIT endpoint because 46 of 200 rows remain ambiguous under the diagnostic symbol-to-identity mapping and the source rows contain no durable IDs.

## 5. Requirement matrix

The complete requirement-by-requirement matrix is:

`reports/nifty200_pit_bounded_certification_matrix_20260923.csv`

Summary:

| Requirement area | Status | Exact bounded result |
| --- | --- | --- |
| authoritative start/end state | FAIL | both sources are complete/hash-valid but roster identity is not durable |
| checkpoint completeness | PASS | 108/108 dates present; 107 intervals |
| membership count integrity | PASS with explicit 201 handling | 58 source-supported 200 states; 50 source-supported 201 DVR states |
| durable and temporal identity | FAIL | 0/21,650 raw roster rows carry durable IDs; 4,356 ambiguous diagnostics |
| event chain | FAIL | 456 canonical accepted events, but 268 raw observations non-canonicalized and 74 critical conflicts |
| effective dates | FAIL | 456/456 populated; 2 effective events fall on package non-session date 2020-07-31 |
| known-at | FAIL for complete observation corpus | 456/456 canonical complete; 651/1,124 bounded observations missing known-at |
| authority and hashes | PASS for accepted evidence | 108/108 checkpoint hashes and 456/456 canonical event hashes valid |
| event/checkpoint reconciliation | PASS as replay evidence | 107/107 durable-ID exact; 92/107 symbol exact; 15 symbol-divergent |
| calendar | FAIL | 3,270 dates audited; all package-only; no authoritative date-level coverage |
| symbol transitions | PASS as transition evidence | 15 divergent intervals reconcile by durable ID; no economic difference demonstrated |
| conflicts/manual review | FAIL | 74 CRITICAL conflicts plus unresolved manual-review observations |
| 201-member handling | PASS | 50 legitimate DVR states preserved, not normalized to 200 |
| import and QA | FAIL | manifest BLOCKED; QA not asserted; approval false |

## 6. Durable identity completeness

### Checkpoint constituent rows

- total bounded roster rows: 21,650
- raw durable IDs in roster rows: 0
- diagnostic exact period-valid symbol matches: 17,284/21,650 (79.833%)
- diagnostic ambiguous symbol rows: 4,356/21,650 (20.167%)
- diagnostic unmatched rows: 0
- strict certification-grade roster identity completeness: 0/21,650

The diagnostic mapping is not used as durable certification. No company-name similarity or fuzzy identity inference was used.

### Canonical events and intervals

- canonical events effective in the bounded period: 456
- canonical ADD / DROP: 228 / 228
- durable instrument ID and ISIN: 456/456
- accepted/certified/non-synthetic: 456/456
- source tier A1: 456/456
- constituent intervals in the current artifact: 332/332 durable-ID rows

The event and interval identity fields are complete for their accepted artifacts. That does not cure the absence of durable identity on the independent checkpoint rosters.

### Symbol transitions

The latest bounded replay evidence records 15 symbol-divergent intervals. All 15 reconcile at durable-ID level and have transition evidence; the transition report represents them as 14 durable transition groups across 15 symbol changes. The remaining symbol differences are therefore not demonstrated economic membership differences. Symbol aliases remain diagnostic and do not rewrite checkpoint source text.

## 7. Event-chain completeness

For effective dates from 2013-04-18 through 2022-03-31:

| Event population | Count |
| --- | ---: |
| canonical events | 456 |
| canonical ADD | 228 |
| canonical DROP | 228 |
| accepted A1 canonical events | 456 |
| durable identity present | 456 |
| announcement date present | 456 |
| known_at present | 456 |
| effective date present | 456 |
| source hash present/valid format | 456 |
| unique event hashes | 456 |
| synthetic canonical events | 0 |

The complete raw observation corpus is not equally admissible:

- bounded event observations: 1,124
- certified observations: 472
- manual-review observations: 384
- unresolved observations: 267
- superseded observations: 15
- missing instrument ID: 1
- missing known_at: 651
- missing effective date: 0
- bounded raw-unresolved observations: 268
  - B1: 267
  - A1: 1, `IBULHSGFIN`, effective 2013-11-15

The 268 rows remain `NOT_CANONICALIZED`; they cannot be treated as harmless because the current fail-closed evidence rules do not permit unresolved observations to close membership gaps.

## 8. Replay certification

The bounded replay result is:

| Replay view | Exact | Divergent |
| --- | ---: | ---: |
| durable ID | 107/107 | 0 |
| symbol diagnostic | 92/107 | 15 |

The 15 symbol-divergent intervals have transition evidence and reconcile at durable-ID level. Examples include the period-bounded transitions `MADRASCEM -> RAMCOCEM`, `SESAGOA -> SSLT -> VEDL`, `PIPAVAVDOC -> RDEL`, `IDFCBANK -> IDFCFIRSTB`, `RNAM -> NAMINDIA`, `TATAGLOBAL -> TATACONSUM`, `NIITTECH -> COFORGE`, `INFRATEL -> INDUSTOWER`, and `CADILAHC -> ZYDUSLIFE`.

The symbol replay was independently recomputed from the 108 current snapshot dates and canonical effective-date events. The durable-ID result is verified against the latest post-August-23 source-resolution evidence; direct independent durable-ID reconstruction from roster bytes is not possible because the rosters omit durable IDs.

## 9. Known-at causality

Canonical bounded events:

- checked: 456
- known_at complete: 456/456
- basis: 456/456 `DATE_ONLY_CONSERVATIVE_NEXT_SESSION`
- known date after effective date: 0
- known date equal to effective date: 0
- known date before effective date: 456
- publication/announcement date missing: 0

The broader bounded observation corpus has 651 missing known_at values. These are not silently promoted to the canonical result.

No canonical lookahead violation was found from the available date fields. However, the next-session calculation depends on a calendar that is not authoritative-certified, so known-at causality is not a passing certification gate.

## 10. Effective-date audit

- canonical effective dates populated: 456/456
- source-backed effective dates: 456/456
- known_at after effective date: 0
- effective dates not marked as package sessions: 2 events
- affected effective date: 2020-07-31
- affected canonical events: `SBICARD ADD` and `VEDL DROP`

The source notice explicitly supplies 2020-07-31, but the current package calendar marks that date as non-session and has no authoritative date-level evidence. Therefore the event date is not rejected as fabricated; its session application is unresolved and blocks strict certification.

## 11. Calendar certification

Bounded calendar audit:

- total calendar dates checked: 3,270
- package sessions: 2,205
- package non-session dates: 1,065
- authoritative-covered dates: 0
- package-only dates: 3,270
- explicitly verified exception dates: 0
- unresolved official-lead dates within bounded period: 0

The bounded period has no admitted complete hashable official NSE date-level calendar corpus. The current calendar rows are all `PACKAGE_ONLY` from the maintained calendar package. The two unresolved official leads in the global artifact are outside this bounded period; they were not carried into the bounded conflict result.

Required calendar roles:

- event publication/effective-date mapping: required for every canonical event;
- session-aware known_at logic: required for every date-only publication;
- market-data completeness: relevant to downstream data certification but not needed to establish the event ledger itself;
- dates irrelevant to membership reconstruction: non-session dates still matter when deciding whether an effective date maps to a valid session.

Decision:

`CALENDAR_BLOCKS_BOUNDED_CERTIFICATION`

A generic weekday calendar is not authoritative evidence. The package-only status alone blocks bounded membership certification under the current rules, and 2020-07-31 is a concrete effective-session ambiguity.

## 12. Legitimate 201-member states

The 50 source-supported 201-member states span:

- first checkpoint: 2016-04-29
- last checkpoint: 2020-05-29
- source-supported state basis: Tata Motors DVR inclusion/exclusion evidence
- extra durable instrument: `NSE-ISIN:IN9155A01020`
- symbol: `TATAMTRDVR`
- certified interval: 2016-04-01 through 2020-06-26
- ADD source: 2016-02-22 A1 press release, effective 2016-04-01
- DROP source: 2020-06-10 A1 press release, effective 2020-06-26

All 50 states are classified `VALID_201_STATE` under the existing coverage evidence. They must not be reduced to 200. No duplicate durable identity is asserted from the roster bytes themselves; the DVR identity is established by the separate A1 event/identity evidence.

## 13. Bounded conflict inventory

The scoped conflict report contains 74 records:

- 74 CRITICAL
- 0 HIGH
- 0 duplicate-add conflicts inside the bounded conflict report
- 74 `REMOVAL_OF_ABSENT_MEMBER`
- all require `MANUAL_REVIEW`

Grouped dates:

`2013-09-27:7; 2013-11-01:1; 2013-11-18:1; 2014-02-28:1; 2014-03-28:8; 2014-09-19:8; 2014-11-28:1; 2015-03-27:3; 2015-05-29:2; 2015-09-28:6; 2015-10-19:1; 2016-04-01:12; 2016-09-30:1; 2016-11-15:1; 2017-05-26:1; 2017-09-05:1; 2018-02-05:2; 2018-04-02:2; 2018-06-29:1; 2018-09-28:2; 2018-12-28:1; 2019-09-27:3; 2019-12-27:1; 2020-03-19:1; 2020-07-31:1; 2020-09-25:2; 2021-03-31:1; 2021-06-30:1; 2021-10-29:1`

Classification:

- `BLOCKING_MEMBERSHIP_CONFLICT`: 74 CRITICAL removal-of-absent-member records;
- `NONBLOCKING_DUPLICATE_OBSERVATION`: 1 bounded ABBOTINDIA A1 duplicate observation at 2022-03-31, because the accepted chain already has ABBOTINDIA active;
- `NONBLOCKING_SYMBOL_ALIAS_CONFLICT`: 15 diagnostic symbol-divergent intervals, with durable-ID exact replay and transition evidence;
- `MANUAL_QA_REQUIRED`: ABBOTINDIA duplicate adjudication and the 268 non-canonicalized raw observations;
- `OUTSIDE_BOUNDED_PERIOD`: OFSS 2024-03-28 duplicate event and its global CRITICAL conflict.

The ABBOTINDIA observation is not allowed to close the 74 critical conflicts. It remains a bounded manual-QA item. OFSS is explicitly outside the bounded end date and is not counted as a bounded blocker.

## 14. Current-contract checkpoint count rule

Under the current monthly checkpoint contract, the bounded expectation is:

- expected checkpoint dates: 108
- authoritative checkpoint dates available: 108
- missing bounded checkpoint dates: 0
- 200-member states: 58
- legitimate source-supported 201-member states: 50
- unclassified count anomalies: 0 in the coverage matrix

This result deliberately excludes the 2012 and post-2022 monthly gaps. It does not change the global 68-gap result and does not weaken the current monthly contract. The bounded count gate is not the reason the candidate fails; durable roster identity, conflicts, calendar, and raw unresolved evidence are.

## 15. Current validator feasibility

The current CLI exposes `--campaign-from` and `--campaign-to`, so date parameters exist. However:

- `build_public_dataset.py` hardcodes the global campaign constants 2012-01-02 through 2026-08-20;
- the build path writes the shared authoritative artifact locations;
- `cli validate` writes the shared derived validation report and consumes global derived JSON;
- there is no current safe bounded output-root and bounded initial-checkpoint seed workflow;
- the current interval artifact is seeded from the unresolved global history, not from the 2013-04-18 roster.

An in-memory simulation of the current `validate_campaign` function used:

- bounded dates 2013-04-18 through 2022-03-31;
- 2,205 package-session dates;
- the explicit DVR expected-count map;
- the 74 scoped conflicts;
- current global canonical events and intervals;
- `calendar_certified=False`.

Result: `BLOCKED`, with 2,280 deduplicated reasons:

- 2,205 member-count reasons caused by using the global interval artifact without a bounded start-state seed; the active set begins at 37 rather than the 2013-04-18 roster;
- 74 unresolved conflict reasons;
- 1 `calendar_not_certified` reason.

The date-parameter surface is therefore a `SOFTWARE_SCOPE_LIMITATION`, not evidence that the historical period itself has 2,205 independent membership failures. The 74 conflicts and calendar failure remain evidence/governance blockers. No software change was made.

A disposable bounded artifact package was not generated because the current build path does not support a clean isolated bounded output root and seed checkpoint without either changing tooling or constructing uncertified identity mappings. No incomplete package was presented as a certification artifact.

## 16. Bounded validation and importer result

Bounded validation:

`BOUNDED_PIT_CERTIFICATION_BLOCKED`

Exact blockers:

1. strict durable identity is absent from all independent checkpoint roster rows;
2. 4,356 checkpoint rows remain diagnostically ambiguous;
3. 268 bounded raw event observations are not canonicalized;
4. 74 bounded CRITICAL membership conflicts remain unresolved;
5. calendar certification is absent for all 3,270 bounded dates;
6. 2020-07-31 has two effective events whose session mapping is unresolved;
7. bounded artifact construction is not supported cleanly by the current global-scope tooling;
8. independent QA has not been performed.

Importer dry-run:

- executed against the current guarded artifact only;
- no database write occurred;
- exact refusal: `Manifest validation is not PASS; import refused`.

A bounded importer dry-run was not attempted against a fabricated or partial package. The current fail-closed refusal is the relevant importer result until a real bounded package exists.

## 17. Independent QA readiness

`BOUNDED_PERIOD_NOT_READY_FOR_INDEPENDENT_QA`

The period is not ready for independent certification QA because the independent reviewer would receive unresolved checkpoint identity, unresolved critical conflicts, incomplete raw event causality, and non-certified calendar provenance. The replay result is useful evidence for a future QA package, not a handoff-ready certification package.

## 18. Safety and excluded periods

Excluded from this audit:

- 2012 anchor and 2012-to-2013 reconstruction;
- post-2022 event completeness and monthly publication gaps.

Those periods remain globally blocked and were not re-investigated.

Safety confirmations:

- production DuckDB/WAL untouched;
- no import performed;
- no Stage A;
- no research, backtest, paper trading, live trading, or broker/API calls;
- no validator/governance/catalogue/data changes;
- no source promotion or synthetic membership;
- no push or merge.

Global campaign status remains unchanged:

```
NIFTY-200 PIT RECONSTRUCTION:
DATA EVIDENCE BLOCKED

INDEPENDENT PIT/DATA QA:
NOT ASSERTED

IMPORT APPROVAL:
NOT GRANTED

CAMPAIGN STAGE A:
BLOCKED
```

## 19. Verification and artifacts

Inputs cross-checked:

- `artifacts/nifty200_pit_v1/validation_report.json`
- `artifacts/nifty200_pit_v1/evidence_manifest.json`
- `artifacts/nifty200_pit_v1/constituent_intervals.parquet`
- `artifacts/nifty200_pit_v1/events_canonical.parquet`
- `artifacts/nifty200_pit_v1/event_observations.parquet`
- `artifacts/nifty200_pit_v1/raw_unresolved_observations.csv`
- `artifacts/nifty200_pit_v1/conflict_report.parquet`
- `artifacts/nifty200_pit_v1/calendar_gap_analysis.csv`
- `artifacts/nifty200_pit_v1/source_catalogue.parquet`
- `reports/nifty200_pit_authoritative_checkpoint_inventory_20260921.csv`
- `reports/nifty200_pit_event_sourced_interval_reconciliation_20260921.csv`
- `reports/nifty200_pit_symbol_transition_resolution_20260922.md`
- `reports/nifty200_pit_august23_source_resolution_20260923.md`

Verification completed:

- checkpoint/date/count/hash checks;
- bounded source-catalogue authority checks;
- independent bounded symbol replay;
- bounded event, raw-observation, identity, conflict, calendar, and 201-member counts;
- current validator bounded in-memory simulation;
- guarded importer dry-run;
- CSV matrix uniqueness/field checks;
- `git diff --check`.

Only the two report artifacts from this audit should be committed.
