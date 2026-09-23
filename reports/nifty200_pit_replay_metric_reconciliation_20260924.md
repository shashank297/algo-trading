# NIFTY-200 PIT replay metric reconciliation and membership-conflict forensic audit

Date: 2026-09-24
Scope: suffix `2016-01-29` through `2022-03-31`, 75 checkpoints and 74 intervals.
Repository state audited: `e426502ba432a8fd779dcf1f73906b07d40c9c97` on `codex/nifty200-pit-authoritative-evidence`.

## 1. Executive result

The old `107/107` and new `8/74` numbers are not contradictory measurements of one common state. `107/107` is a structural transition/delta-level result across the earlier 107-interval campaign; it normalized admitted symbol/name transitions to shared durable identities and did not compare every unchanged checkpoint member's raw period-valid ID. The exact temporary helper that produced that number is not present in the current worktree or reachable Git history, so its exact source is a provenance limitation.

The reproducible suffix replay carries the strict `2016-01-29` checkpoint durable-ID set forward, applies canonical events in `(previous_checkpoint, current_checkpoint]`, and compares the complete carried raw-ID set to the next checkpoint ledger. It yields **8/74 exact raw-ID states and 66/74 divergent raw-ID states**. A direct symbol diagnostic yields 4/74 exact and 70/74 divergent; an admitted-transition alias diagnostic yields 34/74 exact and 40/74 divergent. Of the 66 raw-ID divergences, 26 are raw-ID-only namespace mismatches after admitted alias normalization; 40 remain unresolved economic-membership divergences on the available evidence. None is promoted to a certification-grade identity equivalence.

Certification result: **no certification-grade replay PASS**. The evidence supports 8/74 exact raw-string equality, but the remaining 66/74 require an admissible historical identity namespace that is not available from symbol-only checkpoint roster rows. The 35 absent-removal conflicts remain `MANUAL_QA_REQUIRED`. No production PIT defect is established.

## 2. Metric definitions and semantic difference

| Metric | Definition | Namespace | Result | Classification |
|---|---|---|---:|---|
| Old 107/107 | Structural interval/transition reconciliation; symbol deltas and admitted transition aliases, not complete raw-ID state equality | Transition/durable-ID structural namespace | 107/107 reported previously | `STRUCTURAL_REPLAY_ONLY`; `INVALID_FOR_CERTIFICATION` |
| New 8/74 | Cumulative full-state replay from the 2016-01-29 strict ledger IDs, event rows ordered by effective date/action/event hash, compared to each next strict ledger ID set | Raw period-valid `NSE-ISIN:*` checkpoint namespace | 8/74 exact; 66/74 divergent | `IDENTITY_NAMESPACE_MISMATCH`; not certification-grade |
| Symbol diagnostic | Same cumulative event replay using source symbols only | Symbol namespace | 4/74 exact; 70/74 divergent | Diagnostic only |
| Alias-symbol diagnostic | Same replay after admitted symbol/name transition normalization | Admitted transition-alias namespace | 34/74 exact; 40/74 divergent | Diagnostic only; unresolved membership cases remain |

The numbers must not be used interchangeably. `107/107` should be retracted as a durable full-state certification claim; `8/74` should be retained as a reproducible raw-namespace diagnostic, not interpreted as 66 proven economic membership failures.

## 3. Replay method and reproducibility

Inputs were read-only: `nifty200_pit_checkpoint_identity_ledger_20260923.csv`, `artifacts/nifty200_pit_v1/events_canonical.parquet`, `artifacts/nifty200_pit_v1/conflict_report.parquet`, continuity and structural forensic evidence. The exact old report-only helper was not recoverable; no script name is invented here. Maintained implementation context is `tools/nifty200_pit/intervals.py` and `tools/nifty200_pit/build_public_dataset.py`'s documented continuity mapping and symbol-level discrepancy logic.

The replay uses no fallback from missing IDs to symbols for metric B. It applies ADD/INITIAL_MEMBER as insertion and DROP as removal. It does not access production DuckDB/WAL, broker APIs, research, Stage A, calendar certification, or the 2015-12-31 frontier.

## 4. Interval reconciliation

Metric A is `EXACT_STRUCTURAL_DELTA` for all 74 suffix intervals because the earlier structural result covered all 107 intervals and its remaining admitted transition discrepancy was resolved by the August 2021 source admission. Metric B is exact for 8 intervals and divergent for 66. The complete interval-level evidence is in the companion CSV.

## 5. Root-cause classification

`26` of 66 metric-B divergent intervals are classified `IDENTITY_NAMESPACE_MISMATCH` / `N_EXPECTED_REPRESENTATION_DIFFERENCE`: missing and extra raw IDs have no remaining alias-normalized symbol difference. `40` intervals are classified `UNRESOLVED_ECONOMIC_MEMBERSHIP_DIFFERENCE` after admitted transition aliases are applied. These are unresolved diagnostic divergences, not proven production errors. The affected symbol count in the raw diagnostic diff is `13`; repeated representation drift is counted once.

Root-cause labels are separated as follows: `N_EXPECTED_REPRESENTATION_DIFFERENCE` is a raw period-valid ID change with no remaining alias-normalized symbol difference; `UNRESOLVED_ECONOMIC_MEMBERSHIP_DIFFERENCE` is used for a non-empty alias-normalized symbol diff; `F_EVENT_OR_SOURCE_GAP` is not inferred merely from an absent-drop conflict; and `H_SYMBOL_OR_NAME_TRANSITION` remains in the old structural forensic layer and is not silently converted into raw-ID equality.

## 6. First five raw-ID divergences

- `2016-09-30 -> 2016-10-30`: missing `['NSE-ISIN:INE047A01021']` / extra `['NSE-ISIN:INE047A01013']`; symbols `GRASIM` / `GRASIM`; events: `none`.
- `2016-10-30 -> 2016-11-30`: missing `['NSE-ISIN:INE047A01021']` / extra `['NSE-ISIN:INE047A01013']`; symbols `GRASIM` / `GRASIM`; events: `2016-11-15 ADD CROMPTON NSE-ISIN:INE299U01018 event_hash=f7c6d21081798c335b1d2527fed0998c858a8487426332c8e7ee02495be99ae5; 2016-11-15 DROP CAIRN NSE-ISIN:INE910H01017 event_hash=03d62d5c356188c96bb662e988360d53c919bd77a2147f26b534c1f8994fb4b8`.
- `2016-11-30 -> 2016-12-30`: missing `['NSE-ISIN:INE047A01021']` / extra `['NSE-ISIN:INE047A01013']`; symbols `GRASIM` / `GRASIM`; events: `none`.
- `2016-12-30 -> 2017-01-31`: missing `['NSE-ISIN:INE019A01038', 'NSE-ISIN:INE047A01021']` / extra `['NSE-ISIN:INE019A01020', 'NSE-ISIN:INE047A01013']`; symbols `GRASIM;JSWSTEEL` / `GRASIM;JSWSTEEL`; events: `2017-01-23 ADD RBLBANK NSE-ISIN:INE976G01028 event_hash=53ceb177c163d8a9f643fa595e8f2cf82fdbc9620910f5c93ec55e7680e2491a; 2017-01-23 DROP MFSL NSE-ISIN:INE180A01020 event_hash=047674a407f578a063c91fe24fa0f35cc3386c8fc550342af038c0872fd96d34`.
- `2017-01-31 -> 2017-02-28`: missing `['NSE-ISIN:INE019A01038', 'NSE-ISIN:INE047A01021']` / extra `['NSE-ISIN:INE019A01020', 'NSE-ISIN:INE047A01013']`; symbols `GRASIM;JSWSTEEL` / `GRASIM;JSWSTEEL`; events: `none`.

In the first, third, and fifth examples there is no canonical event in the interval; in the second and fourth, the canonical events concern other symbols. This is direct evidence against treating these raw-ID differences as event-driven membership changes.

## 7. Thirty-five suffix membership conflicts

There are exactly **35** suffix conflicts. All are `REMOVAL_OF_ABSENT_MEMBER`, all are DROP events, and all remain **`MANUAL_QA_REQUIRED`**. The optional companion CSV records conflict identity, source URL, event identity, both metric perspectives, and the conservative set-difference classification. A conflict is not cleared merely because a structural metric matches or because a raw replay interval is exact.

## 8. 201-member checkpoint impact

The suffix contains `50` 201-member checkpoint dates and `50` 201-member later-checkpoint states in the 74 interval comparisons. `TATAMTRDVR` is present as a distinct source symbol: `TRUE`. It is involved in the raw-ID divergence diagnostic: `FALSE`. No ticker collapse or deduplication of `TATAMTRDVR` was performed.

## 9. Namespace audit

| Input namespace | Values | Blank values | Unique values | Repeated values | Interpretation |
|---|---:|---:|---:|---:|---|
| `checkpoint_ledger_suffix` | 15050 | 0 | 335 | 326 | exact-string namespace only; not economic identity proof |
| `canonical_events_suffix` | 310 | 0 | 207 | 79 | exact-string namespace only; not economic identity proof |
| `symbol_transition_durable_ids` | 31 | 0 | 14 | 14 | exact-string namespace only; not economic identity proof |

The checkpoint ledger is period-valid identity evidence for its resolved rows, but authoritative roster source rows are symbol-only. The event chain, continuity links, and transition records therefore occupy related but not automatically interchangeable namespaces. The admitted continuity links are not a universal historical mapping for all 66 raw-ID differences.

## 10. Certification-grade determination

| Determination | Value |
|---|---:|
| Strict raw-ID exact intervals | 8/74 |
| Strict raw-ID divergent intervals | 66/74 |
| Unresolved alias-normalized economic-membership divergences | 40 intervals |
| Certification-grade exact replay PASS | NO |
| Certification-grade claim asserted | NO |

The 40 unresolved intervals are not asserted to be production membership errors; they are the exact remaining alias-normalized diagnostic divergences. The correct status is **not asserted / blocked pending an admissible common identity namespace and manual conflict review**.

## 11. Prior report impact

| Prior claim/report | Impact |
|---|---|
| Earlier `107/107` durable replay claim | `INVALIDATED` as a full-state certification claim; retain only as structural replay history |
| Event-sourced interval reconciliation/governance proposal | `NEEDS_QUALIFICATION`; governance block unchanged |
| Bounded feasibility audit | `NEEDS_QUALIFICATION`; carried replay is not sufficient evidence of durable identity |
| Checkpoint identity certification audit | `NEEDS_QUALIFICATION`; identity row results remain separate, replay cross-check is qualified |
| 2026-09-23 identity-gap analysis | `NEEDS_RECOMPUTATION` / qualification required; its 8/74 raw metric is reproduced, but namespace semantics must be explicit |

No production source or governance file was changed by this audit.

## 12. Production and helper defect determination

`PRODUCTION_PIT_DEFECT_FOUND = NO`. The evidence points to a metric/namespace mismatch and incomplete authoritative identity linkage, not a demonstrated defect in production interval construction. `AUDIT_HELPER_DEFECT = NO` for the reproducible cumulative raw-ID calculation. The temporary audit helper is deleted before commit and is not production code. The missing historical helper that emitted 107/107 remains a reproducibility limitation.

## 13. Calendar and frontier status

Calendar certification remains **PARTIAL_NOT_CERTIFIED**. The 2015-12-31 frontier remains **DEFERRED** and was not analyzed. This report does not grant import approval, independent PIT/data QA, or Stage A readiness.

## 14. Governance, checks, safety, and recommendation

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

Checks performed: 75 suffix checkpoints and 74 intervals asserted; metric-B counts asserted as 8 + 66; 35 suffix conflicts asserted; the 201-member source retained as a distinct symbol; output CSV and Markdown generated from the same deterministic read-only calculation; no production database/WAL or network/broker access used; no push or merge performed.

Recommendation: do not certify NIFTY-200 PIT or run Stage A. First obtain an authoritative, period-valid mapping joining checkpoint roster symbols/rows, event identities, and raw ISIN-derived IDs in one admissible namespace; then manually resolve all 35 absent-removal conflicts and rerun this audit. Until then, retain 8/74 only as a raw namespace diagnostic and treat 107/107 as non-certifying structural history.

## Input hashes

- `checkpoint_identity_ledger`: `7b9e0eff6dc1941cfeb7fe9517662709197bcc9d08807708efd79959d4776747`
- `canonical_events`: `c18c45e4fccf0daebb57a688019bdb9c17ac09c8fb4cc2cb084fb35e4f492fd0`
- `conflict_report`: `1cd51df75ac4f4997daa9fdb1e36187a0d3a40da9a68b2e5a0edbf8fda372815`
- `structural_forensics`: `0fedaa2158020ab60af00a06f28fe83de4270dd6be6b878d5ed943385f2d644e`
