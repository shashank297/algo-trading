# NIFTY-200 bounded checkpoint durable-identity certification

Date: 2026-09-23
Repository: `shashank297/algo-trading`
Worktree: `C:\Python projects\algo trading-authoritative-evidence`
Branch: `codex/nifty200-pit-authoritative-evidence`
Scope: checkpoint-row durable identity only, 2013-04-18 through 2022-03-31 inclusive.

## Decision

`BOUNDED_CHECKPOINT_IDENTITY_BLOCKED`

The ledger is complete and fail-closed: 15,250 / 21,650 checkpoint roster rows (70.439%) have an accepted, explicit, date-valid A1/A2 durable identity. The remaining 6,400 rows are not promoted from current-master, open-ended historical snapshots, company names, fuzzy matches, or predecessor/successor inference.

The result is not a statement that the roster symbols are economically invalid. It is a statement that the supplied checkpoint bytes do not carry durable IDs and the admitted identity corpus does not provide a period-valid proof for every row.

## Population and ledger

| Measure | Result |
|---|---:|
| authoritative checkpoint dates | 108 |
| authoritative roster rows | 21,650 |
| certified unique rows | 15,250 |
| completeness | 70.439% |
| ambiguous diagnostics before temporal filtering | 4,356 |
| ambiguous multiple-identities after accepted temporal filtering | 0 |
| true unresolved rows | 6,400 |
| unique unresolved source symbols | 265 |
| fully certified checkpoints | 76/108 |
| duplicate certified durable IDs within a checkpoint | 0 |

Required ledger: `reports/nifty200_pit_checkpoint_identity_ledger_20260923.csv`
Residual companion: `reports/nifty200_pit_checkpoint_identity_residuals_20260923.csv`

Each ledger row has a deterministic SHA-256 `checkpoint_row_id` derived from checkpoint date, roster source hash/member, source row number, source symbol/name, and raw text. The ledger row count is exactly the 21,650-row bounded roster population; no roster row was dropped.

## Identity proof and temporal join

Accepted proof used for `CERTIFIED_UNIQUE` rows:

- exact source symbol match;
- A1/A2 source tier;
- `has_explicit_historical_interval = true`;
- `valid_from <= checkpoint_date < valid_until` (or open end only where the admitted explicit interval is open);
- certified/accepted identity evidence with durable instrument ID and ISIN.

The broad prior diagnostic was reproduced against all A1/A2 temporal rows. It included current-only master rows and historical snapshot rows whose open-ended representation is not sufficient to prove identity on every later checkpoint date. Those rows were used for diagnosis only. The strict join produced 15,250 unique identities, zero multi-ID matches, and 6,400 rows without accepted period-valid evidence. No software temporal-join correction was required or made.

## Ambiguity root causes

The 4,356 pre-existing diagnostic rows were partitioned by primary root cause. These counts are diagnostic counts and are not certification claims; secondary conditions overlap.

| Primary class | Rows | Interpretation |
|---|---:|---|
| A — same valid ISIN from corroborating sources | 0 | Same-ID source rows were deduplicated before candidate counting; they were not treated as ambiguity. |
| B — multiple distinct ISIN/conflicting first-party rows | 108 | Same instrument ID carried distinct historical ISIN candidates in the diagnostic corpus; no such row was accepted as period-valid certification. |
| C — historical symbol transition | 107 | Existing admitted transition groups were recognized; checkpoint symbols were not rewritten. |
| D — symbol reused by different instruments over time | 0 | No separate period-valid reuse case was proven after the temporal audit. |
| E — alias interval overlap | 0 | Existing scoped transition alias-overlap audit remains clean. |
| F — missing validity boundary | 2,986 | Open-ended historical snapshot candidates cannot be backdated across the checkpoint period. |
| G — non-canonical checkpoint symbol | 0 | No parser rewrite was admitted. |
| H — source-specific formatting | 0 | No deterministic formatting rule was used to create identity. |
| I — current-master contamination | 1,155 | Current-only rows inflated the broad diagnostic; current master was excluded from historical certification. |
| J — genuine unresolved identity evidence | 0 in the 4,356 diagnostic partition | Residual no-evidence rows are reported in the ledger rather than relabeled as ambiguity. |
| K — diagnostic artifact/false ambiguity | 0 as a separate class | False ambiguity is accounted for under I and the temporal-boundary finding under F. |

Secondary diagnostic flags across the 4,356 rows: current-master contamination 3,964; multiple historical IDs 3,093; multiple historical ISINs 3,201; admitted-transition symbols 127. The flags overlap, so they must not be summed.

## Ledger status counts

| Ledger status | Rows |
|---|---:|
| `CERTIFIED_UNIQUE` | 15,250 |
| `AMBIGUOUS_MULTIPLE_IDENTITIES` | 0 |
| `NO_IDENTITY_EVIDENCE` | 6,150 |
| `SYMBOL_NOT_VALID_ON_DATE` | 7 |
| `CONFLICTING_FIRST_PARTY_EVIDENCE` | 0 |
| `CORPORATE_ACTION_REVIEW` | 243 |

`CORPORATE_ACTION_REVIEW` is reserved for rows whose source symbol belongs to an admitted transition group but lacks a direct accepted checkpoint-date identity row. It does not assign the transition durable ID by inference. `SYMBOL_NOT_VALID_ON_DATE` identifies the seven rows with no A1/A2 candidate covering the source symbol/date at all. All other non-certified rows remain `NO_IDENTITY_EVIDENCE`.

## Start and end checkpoints

### Start: `START_CHECKPOINT_BLOCKED`

- date: 2013-04-18
- roster rows: 200
- certified durable identities: 0
- unresolved identities: 200
- ambiguous identities after strict temporal join: 0
- duplicate certified durable IDs: 0
- legitimate multi-security/DVR rows: 0

The source is complete, first-party A1, hash-valid, and has a source-supported 200-row count, but no start roster row has an admitted exact date-valid durable identity interval. The start checkpoint is therefore blocked.

### End: `END_CHECKPOINT_CERTIFIABLE`

- date: 2022-03-31
- roster rows: 200
- certified durable identities: 200
- unresolved identities: 0
- ambiguous identities after strict temporal join: 0
- duplicate certified durable IDs: 0
- legitimate multi-security/DVR rows: 0

The endpoint roster has 200 accepted exact date-valid identities in the existing admitted corpus. This endpoint result does not cure the blocked start or the other 107 checkpoints.

## 201-member/DVR handling

All 50 known source-supported 201-member states were checked without normalizing their counts to 200. The 201-member states are fully identity-certified by this ledger: 50/50. The distinct DVR instrument `NSE-ISIN:IN9155A01020` / `TATAMTRDVR` remains separate from the ordinary Tata Motors security. No company-parent merge or DVR collapse was performed.

## Reused transition evidence

The admitted transition corpus contains 15 evidence-backed symbol transitions across 14 durable-ID groups. Old symbol, new symbol, ISIN, validity dates, source hash, and effective date were retained from the existing transition evidence. The ledger preserves the historical source symbol. Transition evidence was not used to backdate an identity into a checkpoint without a direct accepted date-valid identity row.

## Conflict and replay cross-checks

The bounded conflict population remains 74 CRITICAL `REMOVAL_OF_ABSENT_MEMBER` records before and after this identity audit. Recomputing the conflict inventory with the checkpoint ledger does not prove either event-side membership or an event-side identity correction, so the conservative after-classification is:

| After classification | Count |
|---|---:|
| `RESOLVED_BY_DURABLE_IDENTITY` | 0 |
| `GENUINE_IDENTITY_CONFLICT` | 0 |
| `GENUINE_MEMBERSHIP_CONFLICT` | 0 |
| `DUPLICATE_OBSERVATION` | 0 |
| `SYMBOL_ALIAS_DIAGNOSTIC` | 0 |
| `SOURCE_CONFLICT` | 0 |
| `MANUAL_QA_REQUIRED` | 74 |

No CRITICAL severity was downgraded.

The bounded replay cross-check remains 107/107 exact at durable-ID level and 92/107 exact at symbol level, with 15 symbol-divergent intervals reconciled by the admitted transition evidence. This durable replay result is carried forward from the current admitted evidence; direct independent durable-ID equality cannot be reconstructed from the roster bytes because the rosters contain no IDs.

Canonical event identity remains complete for the bounded canonical event set: 456/456 events have durable instrument ID, ISIN, A1 source, source hash, announcement date, known-at, effective date, certified confidence, accepted review status, and non-synthetic status.

## Sources and safety boundaries

New sources admitted in this workstream: **none**. The ledger reuses already admitted, hash-bound corpus files and the existing symbol-transition/DVR evidence. Source catalogue hash-format failures remain 0; the 108 checkpoint source hashes remain independently verified.

No current-master backdating, company-name similarity, fuzzy matching, unsupported predecessor inference, synthetic membership, governance-rule change, production DuckDB/WAL access, Stage A, research, backtest, paper/live trading, broker API, push, or merge occurred. No code change was made; therefore no regression test was required. The generated ledger/report were checked with deterministic row-count, hash, status, and boundary assertions after generation.

Carry-forward states:

- `CALENDAR: PARTIAL_NOT_CERTIFIED` — calendar work is explicitly out of scope here.
- Global-scope bounded artifact/build tooling remains a `SOFTWARE_SCOPE_LIMITATION`; it was not changed.
- `DATA EVIDENCE BLOCKED`; `INDEPENDENT PIT/DATA QA: NOT ASSERTED`; `IMPORT APPROVAL: NOT GRANTED`; `CAMPAIGN STAGE A: BLOCKED`.

## Final result

`BOUNDED_CHECKPOINT_IDENTITY_BLOCKED`

The endpoint identity is certifiable, but the bounded checkpoint population is not complete and the start checkpoint is blocked. This workstream does not grant PIT certification or Stage A eligibility.
