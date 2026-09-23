# NIFTY-200 residual checkpoint identity gap analysis

Date: 2026-09-23
Worktree: `C:\Python projects\algo trading-authoritative-evidence`
Branch: `codex/nifty200-pit-authoritative-evidence`
Scope: existing bounded checkpoint identity artifacts only; no new source acquisition.

## Decision

`IDENTITY_CERTIFIED_SUFFIX_EXISTS`

`EARLIEST_CONTIGUOUS_IDENTITY_CERTIFIED_START = 2016-01-29`

The identity layer has a fully certified suffix of 75 checkpoints (15,050 roster rows) from 2016-01-29 through 2022-03-31. This does not certify PIT: the scoped direct replay check is not exact, calendar remains `PARTIAL_NOT_CERTIFIED`, 74 critical conflicts remain manual QA, and independent PIT/data QA is not asserted.

## Residual population

| Measure | Result |
|---|---:|
| checkpoint rows | 21,650 |
| certified rows | 15,250 |
| unresolved rows | 6,400 |
| unresolved symbols | 265 |
| checkpoints | 108 |
| fully certified checkpoints | 76 |
| blocked checkpoints | 32 |
| certified checkpoint percentage | 70.439% |

The committed input ledger and residual CSVs were read directly; no residual rows were reconstructed or dropped.

## Chronology

First fully certified checkpoint: 2015-05-29. Last non-fully-certified checkpoint: 2015-12-31. The 76 fully certified checkpoints are not one block:

- 2015-05-29 -> 2015-05-29 (1 checkpoints)
- 2016-01-29 -> 2022-03-31 (75 checkpoints)

The earliest fully certified checkpoint is not a valid contiguous start because later checkpoints through 2015-12-31 are blocked. The longest certified contiguous block is 2016-01-29 -> 2022-03-31 (75 checkpoints).

Detailed chronology: `reports/nifty200_pit_identity_gap_by_checkpoint_20260923.csv`.

## Earliest suffix and replay

| Measure | Result |
|---|---:|
| suffix checkpoints | 75 |
| suffix roster rows | 15,050 |
| suffix certified rows | 15,050 |
| suffix unresolved rows | 0 |
| suffix period length in days | 2253 |
| adjacent replay intervals | 74 |
| direct durable-ID replay exact | 8/74 |
| direct durable-ID replay divergent | 66/74 |
| direct symbol replay exact | 4/74 |
| direct symbol replay divergent | 70/74 |

Replay method: start from the certified ledger IDs/symbols on 2016-01-29, apply only canonical events with `previous < effective_date <= current`, ordered by effective date/action/event hash, and compare each next checkpoint. The direct check therefore invalidates the suffix as an end-to-end replay candidate despite its complete checkpoint identity layer. It is distinct from the earlier carried-forward all-period 107/107 durable replay summary and exposes a current artifact/event-boundary reconciliation gap; no runtime code was changed.

## Symbol concentration

Unique unresolved symbols: 265. Top 20:

| Symbol | Rows | Checkpoints | First unresolved | Last unresolved | Primary reason |
|---|---:|---:|---|---|---|
| ABB | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| ACC | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| ADANIPORTS | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| ALBK | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| AMARAJABAT | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| AMBUJACEM | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| ANDHRABANK | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| APOLLOHOSP | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| APOLLOTYRE | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| ASHOKLEY | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| ASIANPAINT | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| AUROPHARMA | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| AXISBANK | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| BAJAJ-AUTO | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| BAJFINANCE | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| BANKBARODA | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| BANKINDIA | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| BATAINDIA | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| BEL | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |
| BHARATFORG | 32 | 32 | 2013-04-18 | 2015-12-31 | E_MISSING_ALIAS_VALIDITY_BOUNDARY |

Full ranking: `reports/nifty200_pit_identity_gap_by_symbol_20260923.csv`.

Candidate economic instruments were only counted where the existing corpus supplied a candidate ID; no candidate was promoted to a proven economic identity. Fully unknown symbols are those without any A1/A2 master row: 0. Symbol-reuse cases: 0 symbols. Corporate-action/alias cases: 15 symbols.

## Residual root causes

Each residual row has exactly one primary category:

| Class | Rows | Symbols | Checkpoints |
|---|---:|---:|---:|
| A | 0 | 0 | 0 |
| B | 7 | 1 | 7 |
| C | 0 | 0 | 0 |
| D | 0 | 0 | 0 |
| E | 6150 | 249 | 32 |
| F | 243 | 15 | 32 |
| G | 0 | 0 | 0 |
| H | 0 | 0 | 0 |
| I | 0 | 0 | 0 |
| J | 0 | 0 | 0 |

The dominant causes are missing/insufficient dated coverage and unbounded historical aliases. Current-master-only candidates remain inadmissible. No fuzzy matching, company-name inference, or current-master backdating was used.

## Temporal shape

| Pattern | Rows | Symbols |
|---|---:|---:|
| EARLY_ONLY | 5742 | 216 |
| ISOLATED_DATE_GAP | 0 | 0 |
| CONTINUOUS_LONG_GAP | 95 | 4 |
| SYMBOL_TRANSITION_BOUNDARY | 243 | 15 |
| SYMBOL_REUSE_BOUNDARY | 0 | 0 |
| NEVER_CERTIFIED | 320 | 30 |

The residuals are concentrated in the early side of the bounded period, but the single 2015-05-29 island demonstrates that they are not simply a monotonic early-only prefix. The suffix begins only after the 2015-12-31 blocked checkpoint.

## Identity frontier

The frontier is between 2015-12-31 (blocked) and 2016-01-29 (first checkpoint of the longest fully certified suffix). The immediate prior checkpoint has 200 unresolved rows and 200 unresolved symbols. The immediate prior plus the five preceding blocked checkpoints are:

| Checkpoint | Rows | Symbols | Root causes |
|---|---:|---:|---|
| 2015-07-31 | 200 | 200 | B_SOURCE_DATE_DOES_NOT_COVER_CHECKPOINT:1;E_MISSING_ALIAS_VALIDITY_BOUNDARY:192;F_CORPORATE_ACTION_CONTINUITY_UNPROVEN:7 |
| 2015-08-31 | 200 | 200 | B_SOURCE_DATE_DOES_NOT_COVER_CHECKPOINT:1;E_MISSING_ALIAS_VALIDITY_BOUNDARY:192;F_CORPORATE_ACTION_CONTINUITY_UNPROVEN:7 |
| 2015-09-30 | 200 | 200 | B_SOURCE_DATE_DOES_NOT_COVER_CHECKPOINT:1;E_MISSING_ALIAS_VALIDITY_BOUNDARY:192;F_CORPORATE_ACTION_CONTINUITY_UNPROVEN:7 |
| 2015-10-30 | 200 | 200 | B_SOURCE_DATE_DOES_NOT_COVER_CHECKPOINT:1;E_MISSING_ALIAS_VALIDITY_BOUNDARY:192;F_CORPORATE_ACTION_CONTINUITY_UNPROVEN:7 |
| 2015-11-30 | 200 | 200 | B_SOURCE_DATE_DOES_NOT_COVER_CHECKPOINT:1;E_MISSING_ALIAS_VALIDITY_BOUNDARY:192;F_CORPORATE_ACTION_CONTINUITY_UNPROVEN:7 |
| 2015-12-31 | 200 | 200 | B_SOURCE_DATE_DOES_NOT_COVER_CHECKPOINT:1;E_MISSING_ALIAS_VALIDITY_BOUNDARY:192;F_CORPORATE_ACTION_CONTINUITY_UNPROVEN:7 |

Evidence needed at the frontier is dated first-party NSE security-master/bhavcopy identity for each source row, with separate corporate-action/alias evidence where a transition is involved. No acquisition was performed.

## Minimum closure sets

These are planning metrics for extending the suffix backward; they are not evidence acquisitions.

| Backward horizon | Affected checkpoints | Rows to close | Unique symbols | Candidate instruments | Date range |
|---|---:|---:|---:|---:|---|
| 1 | 1 | 200 | 200 | 240 | 2015-12-31 -> 2015-12-31 |
| 3 | 3 | 600 | 200 | 240 | 2015-10-30 -> 2015-12-31 |
| 6 | 6 | 1200 | 212 | 252 | 2015-07-31 -> 2015-12-31 |
| 12 | 12 | 2200 | 225 | 264 | 2015-01-30 -> 2015-12-31 |
| ALL_TO_2013-04-18 | 33 | 6400 | 265 | 304 | 2013-04-18 -> 2015-12-31 |

The one-checkpoint extension alone requires the complete 2015-12-31 roster (200 rows / 200 symbols). Therefore no start materially earlier than 2016-01-29 can be created by resolving only <=5 or <=10 unique symbols. Extending all the way to 2013-04-18 requires all 6,400 residual rows across 265 symbols.

## Start alternatives

| Candidate start | Checkpoints | Rows | Certified | Unresolved | Identity result | Replay result | Calendar |
|---|---:|---:|---:|---:|---|---|---|
| 2013-04-18 | 108 | 21,650 | 15,250 | 6,400 | blocked | not applicable | PARTIAL_NOT_CERTIFIED |
| 2015-05-29 (first full island) | 83 | 16650 | 15250 | 1400 | non-contiguous | not applicable | PARTIAL_NOT_CERTIFIED |
| 2016-01-29 (earliest contiguous suffix) | 75 | 15,050 | 15,050 | 0 | complete | 8/74 durable exact | PARTIAL_NOT_CERTIFIED |
| <=5 unique-symbol improvement | none | — | — | — | no earlier candidate | — | PARTIAL_NOT_CERTIFIED |
| <=10 unique-symbol improvement | none | — | — | — | no earlier candidate | — | PARTIAL_NOT_CERTIFIED |

2013-04-18 diagnosis: 200 unique source symbols; E_MISSING_ALIAS_VALIDITY_BOUNDARY=194; F_CORPORATE_ACTION_CONTINUITY_UNPROVEN=6. The available evidence is either absent for the exact date, too late/too early, unbounded historical snapshot evidence, or a transition-review case. A bulk dated NSE identity file is structurally preferable to per-symbol research, but acquisition is explicitly deferred.

## Conflicts and events

Of 74 bounded `MANUAL_QA_REQUIRED` conflicts, 35 fall inside the identity-certified suffix date range, 2 share an exact checkpoint date with unresolved identity rows, and 10 share an exact fully certified checkpoint date. Inside the suffix, checkpoint identity is nonblocking, but these remain `BLOCKING_MEMBERSHIP_CONFLICT` until event-side membership is resolved; they were not reclassified as identity blockers.

Canonical events effective within the suffix: 310 (155 ADD / 155). Missing or non-A1/certification-field violations in this scoped event set: 0; event identity remains structurally complete for this range.

## Boundaries and decision

`CALENDAR_STATUS = PARTIAL_NOT_CERTIFIED` for every candidate. Known carry-forward blocker: effective date 2020-07-31 remains a package non-session ambiguity. Global-scope bounded tooling remains a software-scope limitation and was not changed.

Recommended next action: `FIRST_RESOLVE_SMALL_IDENTITY_FRONTIER` only if extending the certified start is desired; begin with the 2015-12-31 200-row frontier. Do not proceed to calendar certification until the scoped replay divergence, 35 suffix-range membership conflicts, calendar, and independent QA gates are separately closed.

Identity-planning decision: `IDENTITY_CERTIFIED_SUFFIX_EXISTS`.

Previous commit message assessment: `PREVIOUS_COMMIT_MESSAGE_OVERSTATES_RESULT = YES` — “certify bounded checkpoint identities” can read as a successful bounded certification although the committed report correctly records an overall blocked result. History was not rewritten.

## Safety and verification

- Audit helper classification: `AUDIT_HELPER_ONLY`; temporary report-generation helper, not production/runtime PIT code; it will be removed after generation.
- No new sources were downloaded or admitted.
- No validator, resolver, importer, governance, trading, research, Stage A, broker, production DuckDB, or WAL changes.
- CSV assertions: 21,650 ledger rows; 6,400 residual rows; 108 checkpoint rows in chronology; checkpoint and symbol totals reconcile; deterministic suffix/block calculations completed.
- Calendar work was not performed.
