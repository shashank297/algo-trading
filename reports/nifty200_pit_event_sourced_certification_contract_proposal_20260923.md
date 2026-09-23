# NIFTY-200 PIT event-sourced certification contract proposal

Date: 2026-09-23
Repository: `shashank297/algo-trading`
Worktree: `C:\Python projects\algo trading-authoritative-evidence`
Branch: `codex/nifty200-pit-authoritative-evidence`
Assessment baseline HEAD: `cefccdd9d8abb58a402158940f28bca1be329776`
Mode: report-only governance assessment; no contract, validator, importer, catalogue, or data change is proposed for implementation in this report.

## A. Decision summary

The current evidence supports submitting an event-sourced certification contract for governance review as a proposal. It does not support certifying the NIFTY-200 reconstruction or changing the current validator contract.

```text
EVENT-SOURCED CERTIFICATION CONTRACT:
NOT READY FOR CERTIFICATION; PROPOSAL-ONLY GOVERNANCE REVIEW

NIFTY-200 PIT RECONSTRUCTION:
DATA EVIDENCE BLOCKED UNDER CURRENT CONTRACT

INDEPENDENT PIT/DATA QA:
NOT ASSERTED

IMPORT APPROVAL:
NOT GRANTED

CAMPAIGN STAGE A:
BLOCKED
```

Readiness decision:

`EVENT_SOURCED_CONTRACT_NOT_READY`

Start-date recommendation:

`NO_START_DATE_CHANGE_RECOMMENDED_YET`

Monthly-contract recommendation:

`INSUFFICIENT_EVIDENCE_TO_CHANGE_MONTHLY_REQUIREMENT`

The candidate period for a future governed event-sourced contract is **2013-04-18 through 2022-03-31**, but it is not currently certified. The 2012-01-02 campaign start remains blocked, and no post-2022 period is certified.

## B. Scope, boundary, and safety

This assessment uses only the authoritative evidence worktree and existing local artifacts. It does not authorize or perform:

- validator or governance-semantic changes;
- importer changes or import approval;
- source-catalogue promotion, synthetic membership, fuzzy identity, or reconstructed rosters;
- production DuckDB/WAL access;
- Stage A, research, backtests, paper trading, broker calls, or live trading;
- broad new searches beyond the evidence already recorded;
- push, merge, or deletion of pre-existing reports.

The report is a governance contract proposal, not a certification claim. The existing dirty and untracked reports in the worktree were preserved.

## C. Evidence baseline and checkpoint span

The package validation report is `BLOCKED`. Current measured metrics are:

| Metric | Current evidence |
| --- | ---: |
| source records | 597 |
| source tiers | A1 590, A2 6, B1 1 |
| source hash failures | 0 |
| event observations | 1,556 |
| canonical events | 683 |
| canonical ADD / DROP | 333 / 350 |
| snapshot rows | 21,650 |
| authoritative archived checkpoints | 108 |
| checkpoint span | 2013-04-18 through 2022-03-31 |
| parsed 200-member checkpoints | 58 |
| 201-row checkpoints requiring count/method review | 50 |
| adjacent checkpoint intervals | 107 |
| constituent intervals | 332 |
| conflict records | 132: 131 CRITICAL, 1 HIGH |
| missing/non-200 monthly checkpoints | 68 |
| calendar rows audited | 5,345 |
| unresolved canonical known-at rows | 0 |
| raw observations not canonicalized | 373 |
| unresolved historical identity cases | 1 |
| validation status | `BLOCKED` |
| anchor status | `NOT_ESTABLISHED` |
| calendar status | `PARTIAL_NOT_CERTIFIED` |

The checkpoint inventory contains 109 rows: 108 archived full-roster rows plus one current web-page candidate marked `WEB_ONLY_CURRENT_PAGE_NOT_ADMITTED`. The web candidate is excluded from the authoritative checkpoint count because no local constituent bytes or SHA-256 were admitted.

The authoritative monthly files are independent of the event evidence at the source-file level, but roster rows contain symbols/company names rather than durable ISINs. The inventory therefore records symbol matching as diagnostic only: 17,284 unique symbol matches and 4,356 ambiguous symbol matches across the 21,650 roster rows. This is not durable-ID certification.

## D. What the 107/107 replay result proves

The latest August 23 source-resolution report records a rerun of all 107 adjacent checkpoint intervals:

- 107/107 exact at durable-ID level;
- 92/107 symbol-only exact;
- 15/107 symbol-only divergent;
- the former single durable-ID divergence was resolved by the authoritative 2021-08-23 release;
- the 2021-08-31 to 2021-09-30 interval is reproduced by six ADD and six DROP events from page 14 of that release.

The symbol-only divergence is largely explained by period-bounded first-party identity transitions such as `MADRASCEM -> RAMCOCEM`, `SESAGOA -> SSLT -> VEDL`, `UNIPHOS -> UPL`, `PIPAVAVDOC -> RDEL`, `IDFCBANK -> IDFCFIRSTB`, `RNAM -> NAMINDIA`, `TATAGLOBAL -> TATACONSUM`, `NIITTECH -> COFORGE`, `INFRATEL -> INDUSTOWER`, and `CADILAHC -> ZYDUSLIFE`. Those transitions are represented as evidence-backed diagnostic aliases; they do not permit rewriting source roster text or treating current identity as historical proof.

The preserved `nifty200_pit_event_sourced_interval_reconciliation_20260921.csv` predates the August 23 resolution and still contains the prior `91/16` and `NOT_CERTIFIABLE` diagnostic values. It remains an historical artifact. The current `92/15` and `107/107` results are taken from the later source-resolution report and its regenerated package evidence; the stale report was not silently rewritten.

## E. What the 107/107 result does not prove

It does not prove:

- that the 2012-01-02 campaign anchor exists or is correct;
- that every date outside 2013-04-18 through 2022-03-31 has authoritative membership evidence;
- that 2012-01 through 2013-03 can be reconstructed without an authoritative initial state;
- that post-2022 event sourcing is complete, since there are no admitted later independent full-roster checkpoints;
- that all 50 201-row checkpoints are valid 201-member methodology exceptions;
- that all duplicate, conflict, and historical identity cases are resolved;
- that the package uses a complete authoritative NSE session/holiday calendar;
- that independent PIT/data QA has occurred;
- that the importer may run, or that Stage A may begin.

The exact-set replay result is therefore evidence of technical feasibility over the observed checkpoint span, not a certification of the campaign range.

## F. Monthly publication-model assessment

The existing 68-row classification has exactly this distribution:

| Class | Meaning | Count |
| --- | --- | ---: |
| A | full roster found | 0 |
| B | roster exists but acquisition failed | 0 |
| C | official event notice only | 16 |
| D | invalid/error artifact | 11 |
| E | no evidence of monthly full-roster publication | 41 |
| F | governance-only | 0 |

The periods are:

- 15 blockers in 2012-01 through 2013-03: 11 class D and 4 class C;
- 53 blockers in 2022-04 through 2026-08: 41 class E and 12 class C.

The publication archive comparison covers 57 candidate months from 2021-12 through 2026-08. Four have an admitted NIFTY-200 member (`2021-12` through `2022-03`); 53 post-boundary ZIP candidates contain other products and no NIFTY-200/CNX-200 member. This proves a change in the observed archive contents, not formal discontinuation or relocation of the NIFTY-200 product.

Decision: `INSUFFICIENT_EVIDENCE_TO_CHANGE_MONTHLY_REQUIREMENT`.

The proposed event-sourced contract can be considered by governance, but the strict monthly full-roster requirement remains unchanged until a versioned governance decision accepts a replacement and its evidence gates.

## G. Anchor treatments

### Treatment A — retain 2012-01-02 and remain blocked

Evidence required: an authoritative complete 2012-01-02 membership set or a governed backward-anchor proof; a complete causal chain to 2013-04-18; period-valid durable identity for every affected security; complete calendar evidence; and closure of the relevant conflicts and gaps.

Benefits: preserves the original campaign scope and avoids truncation.

Risks: current anchor evidence is `NOT_ESTABLISHED`; backward reconstruction can introduce survivorship or lookahead error if endpoint facts are treated as historical state.

Feasibility: possible in principle, not demonstrated by the current corpus.

Current satisfaction: **No**. The current anchor replay has 2,941 sessions outside the expected 200-member state and is diagnostic, not certification evidence.

### Treatment B — start at the first complete authoritative checkpoint, 2013-04-18

Evidence: the first admitted full-roster archive is `indices_dataApr2013.zip`, containing `cnx200_Apr2013.csv`; it is independently hashed and has 200 parsed unique symbols.

Benefits: removes the unresolved initial-state dependency for the candidate period and preserves exact endpoint evidence through 2022-03-31.

Risks: excludes the 2012-01-02 through 2013-04-17 campaign period; does not resolve post-2022 gaps, identity evidence, conflicts, 201-row checkpoints, or calendar certification.

Feasibility: the strongest candidate start, but only as a future governed scope.

Current satisfaction: **No**. The start is evidenced, but the proposed contract’s identity, conflict, calendar, QA, and post-period gates are not satisfied.

### Treatment C — retain 2012 through governed backward-anchor proof

Evidence required: a future source-bound proof with exact 2012 membership, source hashes, causal known-at, exact effective dates, durable identity, no B1 dependency, and independent reconciliation to 2013-04-18.

Benefits: could preserve the full campaign without silently inventing a roster.

Risks: high evidentiary burden; a backward proof can fail closed for one missing member or one unresolved date/identity conflict.

Feasibility: not currently assessable as a passing route.

Current satisfaction: **No**; treat as a future evidence target, not a present assumption.

## H. Post-2022 assessment and independent verification

The 53 post-2022 monthly blockers remain. The current canonical ledger has 147 events with effective dates on or after 2022-04-01; all 147 have durable instrument ID, ISIN, effective date, and conservative known-at in the canonical artifact. This proves accepted event-row completeness, not completeness of the post-2022 event universe.

The broader observation set has 267 post-2022 observations, of which 105 lack accepted known-at. There are no admitted later independent full-roster checkpoints against which the post-2022 event ledger can be tested. The 2022-04 onward archive-pattern comparison is negative evidence about the acquired ZIP contents only.

A future post-2022 contract should require at least one of the following independent controls, preferably more than one:

- a periodic official complete NIFTY-200 roster with preserved bytes and hash;
- a current first-party constituent endpoint captured and versioned at each review;
- semiannual review against the official rebalancing cadence, with off-cycle events separately logged;
- independent governance review of the event ledger and identity map;
- periodic manual reconciliation of the reconstructed set to first-party membership evidence.

No such later independent verification is asserted by this report.

## I. Calendar blocker, separated by period

The calendar audit contains 5,345 rows: 5,337 `PACKAGE_ONLY`, 6 `VERIFIED_EXCEPTION`, and 2 `UNRESOLVED_OFFICIAL_LEAD`.

| Period | Calendar evidence | Readiness impact |
| --- | --- | --- |
| 2012-01 through 2013-03 | 455 rows: 453 package-only and 2 unresolved official leads (`2012-01-07`, `2012-03-03`) | blocks causal known-at/session mapping for the unresolved anchor period and can alter session counts and first-effective dates |
| 2013-04 through 2022-03 | 3,287 package-only rows | the candidate replay span has no admitted complete official date-level corpus; weekday alignment is not equivalent to authoritative calendar proof |
| 2022-04 through 2026-08 | 1,603 rows: 1,597 package-only and 6 verified exceptions | post-2022 event timing and session counts remain non-certified despite the verified exceptions |

This matters to `known_at`, effective-session assignment, session counts, survivorship windows, and import readiness. Weekdays, exchange-calendar package output, and inferred next sessions must not be relabeled as authoritative NSE calendar evidence.

## J. Durable identity and event-chain counts

The exact current numerators and denominators are:

| Population | Durable identity result |
| --- | --- |
| canonical events | 683/683 have instrument ID and ISIN; all 683 are A1, accepted, non-synthetic |
| canonical ADD / DROP | 333/333 and 350/350 have durable identity |
| canonical post-2022 events | 147/147 have durable identity |
| constituent intervals | 332/332 have durable instrument ID and certified interval rows |
| adjacent replay intervals | 107/107 exact at durable-ID level in the latest rerun |
| all event observations | 1,555/1,556 have an instrument ID in the observation artifact; this is not acceptance certification |
| certified historical event observations | 719/1,556 are certified; 464 are manual-review rows and 373 are retained raw-unresolved/B1 discovery rows in the package metrics |
| unresolved historical identity cases | 1 |
| unresolved conflicts | 132 total: 130 removal-of-absent-member, 1 duplicate-add, 1 coverage-gap |

The period-valid identity gap remains material because roster rows themselves lack durable identifiers and because the historical identity map is not a substitute for source-side identity. The single unresolved historical identity case, 4,356 ambiguous symbol matches, 50 count-review checkpoints, and the unresolved conflicts prevent a claim that every affected security has a complete certification-grade chain.

The canonical ledger has no B1 dependency for accepted canonical events. The retained 373 raw-unresolved observations must remain non-canonical and cannot be used to close a gap.

## K. Known-at, effective dates, and conservative timing

For canonical events:

- known-at: 683/683 populated;
- effective date: 683/683 populated;
- known-at basis: 683/683 `DATE_ONLY_CONSERVATIVE_NEXT_SESSION`;
- post-2022 canonical known-at/effective: 147/147 complete.

For all 1,556 event observations:

- effective date: 1,556/1,556 populated;
- known-at: 720/1,556 populated and 836/1,556 absent;
- post-2022 observations: 267 total and 162 with known-at, leaving 105 without accepted known-at.

The canonical zero-unresolved count therefore means no canonical row is missing its required fields. It does not mean every raw observation is causally timed. Date-only publication records are conservatively placed at the next session, but the session calendar is only partially certified. Exact next-session ambiguity remains a contract gate.

## L. Symbol transitions, corporate actions, and 201-member handling

The 15 symbol-divergent intervals include 14 evidence-backed durable-ID transition groups plus the resolved 2021-09-30 six-for-six membership event group. Symbol text remains untouched. Transition aliases are bounded at the evidenced effective date and are diagnostic unless independently promoted by governance.

The proposed contract must explicitly require:

- old and new symbol/name, durable identity, and bounded valid-from/valid-until dates;
- corporate-action, merger, demerger, renaming, and reconstitution evidence to be distinguished;
- no current-master backdating or fuzzy matching;
- exact reconciliation by durable ID, with symbol comparison retained as a diagnostic view;
- explicit adjudication for each 201-row checkpoint rather than automatic normalization to 200.

The 50 checkpoints with 201 unique parsed rows are not a license to drop a row, call it an exception, or force a 200-member target without an official methodology and source-bound explanation.

## M. ABBOTINDIA and OFSS classification

### ABBOTINDIA

Classification: `NONBLOCKING_BUT_REQUIRES_MANUAL_QA`.

The 2022-03-31 ADD observation duplicates an already accepted 2020-06-26 ADD; the chain later contains an accepted 2023-09-29 DROP. The row has durable identity and does not change the reconstructed membership state for the endpoint. It remains a raw duplicate with no admitted prior DROP, withdrawal, correction, or supersession that explains why it was published again. Manual QA must decide whether the notice is a restatement, duplicate, or correction before a full contract can pass.

### OFSS

Classification: `NONBLOCKING_BUT_REQUIRES_MANUAL_QA`.

The 2024-03-28 ADD observation follows an accepted 2021-03-31 DROP and 2022-03-31 ADD, so the accepted event chain already has the security active. The observation is durable-ID linked but remains an unexplained duplicate/manual-review row. Manual QA must adjudicate the duplicate or supersession semantics.

These classifications mean nonblocking to the affected endpoint state when the accepted canonical chain is used. They do not waive the global unresolved-conflict gate: the package still has 132 unresolved conflicts, including a duplicate-add conflict, so current certification remains blocked.

## N. Proposed event-sourced certification contract

This section is a proposal only. No validator or governance semantics are changed.

### N1. Scope and period

The candidate certification period is 2013-04-18 through 2022-03-31, beginning at the first admitted complete full-roster checkpoint. 2012-01-02 is retained as an explicitly blocked predecessor period. Post-2022 is a separate extension tier and is not included in the candidate certified period.

### N2. Initial checkpoint

The initial checkpoint must be a byte-preserved first-party roster with SHA-256, exact effective-as-of date, member-count basis, and independent QA. The 2013-04-18 CNX-200 CSV is the candidate initial checkpoint, not a current certification approval.

### N3. Event chain

Every membership change between checkpoints must be represented by an A1/A2 event source with source URL, raw hash, source page or record, action, durable identity, exact effective date, and causal known-at. The contract must define a maximum permitted chain duration without an independent full checkpoint; no indefinite inference across missing checkpoints is allowed.

Off-cycle evidence, replacement reviews, corporate actions, corrections, and supersessions must be explicit event types. Conflicting notices must fail closed until adjudicated.

### N4. Identity

Every affected security must have a period-valid durable ID, with evidence for old/new symbols and names. Symbols alone, current security-master membership, fuzzy names, and B1 data are not acceptable substitutes.

### N5. Reconciliation

Replay must reproduce every independent authoritative checkpoint exactly by durable ID. Symbol equality is diagnostic. The contract requires zero unexplained HIGH/CRITICAL membership divergence and explicit disposition of every 201-row checkpoint.

### N6. Timing and calendar

Known-at must be causally no later than the effective session. Date-only evidence may use a conservative next-session policy only when the authoritative session calendar is admitted and hashed. The calendar must be separately certified; a maintained package alone is insufficient.

### N7. QA, import, and rollback

Independent PIT/data QA must verify source hashes, event lineage, identities, dates, replay, conflicts, and calendar. Import approval must require a passing manifest after QA; Stage A must remain blocked otherwise. A versioned dataset and manifest must support rollback to the prior approved evidence version without mutating source history.

### N8. Governance versioning

The contract, its acceptance criteria, and any replacement of monthly checkpoints require a versioned governance approval. A report, a local replay, or a current-page check cannot change validator semantics by itself.

## O. Minimum governance gates and unresolved requirements

The candidate contract is not ready because the following gates are not all satisfied:

- authoritative start is available only from 2013-04-18; the original 2012 start is unresolved;
- complete accepted A1/A2 chain is not established across the full intended range;
- 132 conflicts remain unresolved;
- 50 full-roster count/methodology reviews remain;
- 53 post-2022 monthly gaps remain and there are no independent later full checkpoints;
- calendar evidence is `PARTIAL_NOT_CERTIFIED`;
- one historical identity case remains unresolved and roster identity is symbol-only;
- ABBOTINDIA and OFSS require manual QA;
- independent QA is not asserted;
- importer approval is false and the importer dry-run refuses the package;
- no B1 source may be used to fill any of these gaps.

## P. Decision matrix

Qualitative ratings are relative to the current evidence and are not certification scores.

| Option | Evidence strength | Survivorship risk | Lookahead risk | Reproducibility | Auditability | Operations | Free-data feasibility | Residual blockers |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Current strict monthly contract | high where admitted files exist | low if complete | low if calendar/known-at pass | high | high | high | low-to-medium | 68 missing checkpoints, 50 count reviews |
| Event-sourced from 2013-04-18 | medium, exact replay observed | medium until every event/identity is closed | medium until calendar and causal known-at are certified | medium-high | medium-high | medium | medium | conflicts, identity, calendar, no later checkpoints |
| Event-sourced with 2012 retained but blocked | low for 2012; medium thereafter | high/unbounded in blocked span | high if backward inference is used | low-medium | low-medium | high | low | anchor, calendar, chain, identity |
| Shorter certified period plus event-sourced extension | medium for 2013-2022 only | medium outside certified span | medium outside certified span | medium-high | high if tiered | high | medium | current gates still fail; post-2022 extension unverified |
| No governance change | high control strength | low by fail-closed exclusion | low | high | high | low operationally | low | no certified campaign range |

The matrix supports continued governance review of a tiered event-sourced design, but not approval of a semantic replacement today.

## Q. Readiness, campaign, import, and activity status

| Decision | Status |
| --- | --- |
| event-sourced contract | `EVENT_SOURCED_CONTRACT_NOT_READY` |
| NIFTY-200 PIT certification | blocked |
| proposed certifiable period | candidate only: 2013-04-18 through 2022-03-31 |
| original campaign start 2012-01-02 | blocked; anchor not established |
| independent PIT/data QA | `NOT_ASSERTED` |
| importer approval | not granted; dry-run refuses non-PASS manifest |
| Stage A | blocked |
| research/backtest/paper/live trading | not run |
| broker/API calls | not run |
| production DuckDB/WAL | untouched |
| governance/validator semantics | unchanged |

## R. Artifacts, verification, and handoff

The assessment used and cross-checked:

- `artifacts/nifty200_pit_v1/validation_report.json`;
- `artifacts/nifty200_pit_v1/evidence_manifest.json`;
- `artifacts/nifty200_pit_v1/blocker_ledger.csv`;
- `artifacts/nifty200_pit_v1/unresolved_gaps.csv`;
- `artifacts/nifty200_pit_v1/constituent_intervals.parquet`;
- `artifacts/nifty200_pit_v1/events_canonical.parquet`;
- `artifacts/nifty200_pit_v1/event_observations.parquet`;
- `artifacts/nifty200_pit_v1/conflict_report.parquet`;
- `artifacts/nifty200_pit_v1/calendar_gap_analysis.csv`;
- `artifacts/nifty200_pit_v1/source_catalogue.parquet`;
- `reports/nifty200_pit_authoritative_checkpoint_inventory_20260921.csv`;
- `reports/nifty200_pit_publication_archive_comparison_20260921.csv`;
- `reports/nifty200_pit_monthly_checkpoint_classification_20260921.csv`;
- `reports/nifty200_pit_event_sourced_interval_reconciliation_20260921.csv`;
- `reports/nifty200_pit_divergent_interval_forensics_20260922.md`;
- `reports/nifty200_pit_symbol_transition_resolution_20260922.md`;
- `reports/nifty200_pit_missing_event_resolution_20260923.md`;
- `reports/nifty200_pit_august23_source_resolution_20260923.md`;
- `reports/nifty200_pit_certification_governance_options_20260921.md`.

Verification performed for this report:

- current branch, HEAD, origin/main relationship, and worktree state inspected;
- current JSON, CSV, and Parquet metrics read from the authoritative worktree;
- checkpoint, publication, monthly-classification, calendar, conflict, event, and identity counts independently recomputed;
- current symbol replay recomputed over all 107 checkpoint intervals;
- no rebuild was performed because the evidence inputs were unchanged;
- report-only scope maintained;
- no push or merge performed.

The report should be committed as a docs-only local governance artifact. The commit must include this file only and must not stage the pre-existing dirty or untracked reports.

Final conclusion: the evidence justifies a versioned event-sourced contract proposal for governance review, but it does not justify a start-date change, validator change, import approval, Stage A, or certification claim.
