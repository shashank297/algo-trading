# Bounded anchor wiring fix — blocked before implementation

Implementation result: `ANCHOR_WIRING_FIX_FAILED`.

Overall result: `BOUNDED_PIT_VALIDATION_BLOCKED`.

No production fix, test change or commit was made. The wiring diagnosis remains correct, but the available certified membership checkpoint is not a certified **causal replay seed**. Implementing real-data integration under the requested existing-schema/admissibility constraints requires evidence-backed seed availability or an explicitly agreed seed-input contract; neither is currently present. No timestamp or admissibility decision was invented.

## Repository and preservation

Worktree: `C:\Python projects\algo trading-authoritative-evidence`.

Branch: `codex/nifty200-pit-authoritative-evidence`.

Starting and ending HEAD: `4ad334ef15baa3d5dc3aa8bae9c90bb2c30027c3`.

Staged changes: none. Existing unstaged changes remain the two reports `reports/nifty200_pit_2012_anchor_forensics_20260911.md` and `reports/nifty200_pit_initial_anchor_20120102.md`. Complete starting untracked inventory is included in the CSV, including preserved restricted test-fixture directories. No reset, stash, branch switch, cleanup or staging was performed.

The current root-cause Markdown was read and the complete 2,386-row root-cause CSV was parsed. Their hashes remain:

- Markdown: `0137186ff70b829b49a1ee45e53f0fd8f0c6f3a0e3d13c8d81d2f43889fe8235`.
- CSV: `f8c01ab77ab3f11ff2d7cc7a4b0fa764f516f0078c1956961d8a7d30a07844d7`.

All existing report/package/derived/PIT-source-code files included in the entry hash inventory were preserved; exact entry hashes are in the CSV. Only these two requested new reports are added to the worktree. Temporary inspection/rendering scripts and diagnostic state are confined to the OS temporary directory.

## Current code still matches the diagnosis

`PRIMARY_ROOT_CAUSE = PIPELINE_WIRING_GAP`.

| Boundary | Exact current code | Current arguments / representation | Required handoff |
|---|---|---|---|
| Validator entry | `tools/nifty200_pit/validation.py:validate_campaign:49` | Existing intervals, events, date bounds, anchor Boolean, calendar/conflict/source inputs | Evidence-validated bounded initial state must reach interval construction before validation |
| CLI entry | `tools/nifty200_pit/cli.py:main:124–126` | Loads global event/interval/conflict JSON; dates alone do not load a checkpoint | Bound-selected, admissible seed must be passed explicitly; no such loader currently exists |
| Roster loader | `tools/nifty200_pit/build_public_dataset.py:parse_monthly_snapshots:1601`, called by build_dataset at 2877 | Official roster dictionaries: snapshot_date/symbol/company/source fields | Not a typed causal seed; roster has no durable ID or known_at |
| Identity certificate representation | `reports/nifty200_pit_checkpoint_identity_ledger_20260923.csv` | checkpoint_date, durable_instrument_id, CERTIFIED_UNIQUE status, source/identity hashes and validity | Identity certification alone does not establish historical availability |
| Broken assembly call | `tools/nifty200_pit/build_public_dataset.py:build_dataset:2990` | `build_intervals(reconciliation.events, horizon_start=CAMPAIGN_FROM, horizon_end=CAMPAIGN_TO)` | An explicit evidence-backed initial-state input, not events alone |
| Empty state | `tools/nifty200_pit/intervals.py:build_intervals:35/45` | No seed parameter; `active = {}` | Initialize from a verified checkpoint state; never infer it from the first event |
| Typed interval schema | `tools/nifty200_pit/models.py:ConstituentInterval:162` | Requires known_from/known_at alongside identity/effective dates/confidence | Source-backed timing/lineage must be retained when representing checkpoint members |
| Existing admissibility gate | `tools/nifty200_pit/validation.py:validate_campaign:118–120` | Rejects missing known_at, synthetic or non-certified intervals | Must not be bypassed merely because identity rows are certified |

No production certified-checkpoint loader or explicit seed-admissibility routine was found in `tools/nifty200_pit`. The CSV parsing in the earlier audit is a diagnostic membership check, not a maintained causal seed loader. The global reverse-anchor forensics at build_public_dataset.py:2242 is expressly non-authoritative and returns NOT_ESTABLISHED, not a bounded seed certificate.

## Exact prerequisite missing

The 2016-01-29 identity ledger contains **200 rows, 200 unique durable IDs, all CERTIFIED_UNIQUE**. Its hash is `7b9e0eff6dc1941cfeb7fe9517662709197bcc9d08807708efd79959d4776747`.

Its schema has no `known_at`, `known_from`, `publication_date`, `publication_timestamp` or `seed_available_at` column. The dated identity validity fields prove identity on the checkpoint date, not that the complete roster was known at the requested historical replay instant. Current downloaded_at/retrieved_at metadata is acquisition provenance, not a historical publication timestamp.

The separate package anchor artifacts were checked directly:

| Artifact | Scope / disposition | Finding |
|---|---|---|
| `artifacts/nifty200_pit_v1/initial_anchor_20120102.parquet` | Target 2012-01-02, later checkpoint 2013-04-18; 200 rows | NOT_ASSERTED, eligible_for_replay=False; wrong bound |
| `artifacts/nifty200_pit_v1/initial_anchor_evidence.parquet` | Target 2012-01-02, later checkpoint 2013-04-18; 200 rows | NOT_ASSERTED, eligible_for_replay=False, all known_at blank |
| `artifacts/nifty200_pit_v1/anchor_replay_candidate.parquet` | Target 2012-01-02; 200 diagnostic rows | NOT_ASSERTED, eligible_for_replay=False; some event knowledge fields cannot certify a checkpoint seed |
| `artifacts/nifty200_pit_v1/anchor_replay_sessions.parquet` | Global diagnostic session counts | Does not contain a certified 2016 starting-state/availability contract |

These artifacts were read through DuckDB `:memory:`. None was promoted or rewritten.

This does not reopen the completed 75-checkpoint membership certification, revoke 74/74 historical economic replay, or claim that the roster/identity evidence is missing. It distinguishes those accepted historical audit results from a causally admissible executable seed.

## TDD status: no fabricated RED or GREEN

The Python testing skill was consulted for the requested TDD workflow. Work pauses before production edits: the task requires a correctly admissible checkpoint and prohibits bypassing anchor validation. No certified real-data seed satisfying that precondition was located, and the existing caller/API does not accept one.

- Proposed regression location/name: `tests/test_nifty200_pit_intervals.py::test_bounded_interval_builder_seeds_from_certified_start_checkpoint`.
- Test added: **NO**.
- RED run/output: **NOT_RUN**. No TypeError, incompatible-fixture error or artificial expected-membership assertion is represented as the required behavioral RED.
- Production files changed: **NONE**.
- GREEN run: **NOT_RUN**.
- Seed-behavior removal/restoration verification: **NOT_RUN**.
- Root-cause fix verified: **NO**.

A constructed representative fixture could test a newly specified seed contract, but it would not prove that the actual certified ledger can be loaded under existing causal admissibility checks. This task does not silently substitute an API-only unit-test success for real-data anchor integration.

To resume narrowly, first identify an already admitted hash-bound source/artifact proving checkpoint availability, or explicitly agree the evidence-backed seed input/availability contract. Then write the single regression against the real assembly boundary, verify empty-state RED, add only the explicit seed argument and required call-site wiring, and perform the requested green/mutation/regression/full verification. Do not use current retrieval timestamps, synthetic INITIAL_MEMBER events, inferred publication times or an unconditional anchor flag.

## Fresh actual bounded validator execution

The unchanged actual `validate_campaign` was executed twice from this worktree using the same certified-population/stored-package inputs as the previous bounded diagnostic. No global dataset builder, parser reconstruction, CLI output writer or importer was run.

Inputs: 310 canonical effective-date-selected events, 231 overlapping stored intervals, 36 bounded/undated stored conflicts. Source errors were freshly verified as an empty list. Common arguments: `campaign_from=date(2016,1,29)`, `campaign_to=date(2022,3,31)`, `initial_anchor_established=False`; all other inputs were preserved.

| Execution | Existing calendar input | Prior result | Fresh current result |
|---|---|---|---|
| No-calendar bounded call | None / no certified provenance | BLOCKED, 40 reasons | BLOCKED, 40 reasons; status, reasons and metrics identical |
| Existing diagnostic-date bounded call | Same 1,529 dates and 200/201 expected-count map, same diagnostic provenance, calendar_certified=False | BLOCKED, 38 reasons | BLOCKED, 38 reasons; status, reasons and metrics identical |

The existing date list and expected-count map were read from the persisted diagnostic output, not regenerated or newly certified. Using that same input preserves the requested before/current comparison. There is no implemented AFTER version; the fresh current runs must not be labelled successful post-fix validation.

| Requested state | Before | Current, no implementation |
|---|---|---|
| ANCHOR_INTEGRATED | NO | NO |
| INITIAL_STATE_EMPTY at interval-builder initialization | YES | YES |
| INTERVAL_CONSTRUCTION_EVALUABLE from a certified causal bounded seed | NO | NO |
| ECONOMIC_REPLAY_STATUS | NOT_EVALUABLE | NOT_EVALUABLE |

Empty builder initialization is different from the old global package having 76 active IDs at the first bounded checkpoint after replaying earlier changes. Those 76 IDs are not the complete 200-ID certified starting state.

The production validator returns PASS/BLOCKED only. Complete economic replay's NOT_EVALUABLE is an audit assessment, not a new production enum or a hidden three-Boolean function. Fresh `count_validation_evaluable=False` is exactly the supplied false anchor flag; zero count failures must not be read as PASS.

## Exactly one next earliest blocking predicate

`NEXT_EARLIEST_BLOCKING_PREDICATE = tools/nifty200_pit/validation.py:validate_campaign:106 — initial_anchor_established must be True; actual value remains False.`

Its reason is `initial_anchor_not_established`; metric at line 130 remains false. The underlying unmet requirement is an integrated causally admissible seed, not a lack of certified checkpoint identities. No predicate is reported as having advanced past the unchanged wiring defect.

Remaining independent conditions, not fixed:

| Blocker | Present |
|---|---|
| CALENDAR_INTEGRATION_BLOCKER | YES |
| STALE_CONTINUITY_ARTIFACT_BLOCKER | YES |
| STALE_CANONICAL_EVENT_BLOCKER | YES |
| MANIFEST_BLOCKER | YES |
| OTHER_BLOCKER | YES: no integrated causal seed; complete accepted namespace/disposition layer still not executable; retained interval/conflict package blockers |

Legitimate 201-member periods/TATAMTRDVR are unchanged. No continuity or calendar artifact, canonical event, conflict, catalogue or manifest was refreshed.

## Verification and commit decision

Fresh source hash validation: **603 registered records / 583 distinct hashes; zero missing or mismatched bytes**. All resolved source paths were checked to remain inside the authoritative worktree before reading bytes. Fresh actual validator status/reasons/metrics reproduced both earlier executions. Existing reports/artifacts/source files were checked for preservation.

New regression, focused PIT/calendar/storage tests, full pytest, Ruff, Mypy, Pyright, compileall and deterministic **seeded** bounded replay were **NOT_RUN** in this stopped implementation attempt. They are not claimed passed. Existing regression/static evidence is not substituted for the required post-implementation verification. Previously reported broad Mypy errors and Pyright warnings were not fixed, suppressed or reclassified. Whitespace verification of the unchanged tracked diff is recorded separately in the CSV.

Commit SHA: **NONE**. No implementation/test change exists to commit, and the TDD/fresh full-verification prerequisites were not satisfied. No empty or report-only commit was created.

## Safety and required direction

Production market_data.duckdb/WAL was not opened, hashed, modified or imported into. No Stage A, strategy optimization, actual research/backtest, paper/live trading, broker API, new source acquisition, governance change, push or merge occurred. All existing local changes and historical reports were preserved.

Required direction: provide the already admitted causal seed-availability artifact/path, or explicitly authorize defining the minimal evidence-backed seed-input contract with actual-data integration remaining blocked until its availability evidence is satisfied. This is not a request for broad historical research or permission to relax validation.

```text
INDEPENDENT PIT/DATA QA: NOT ASSERTED
IMPORT APPROVAL: NOT GRANTED
CAMPAIGN STAGE A: BLOCKED
```
