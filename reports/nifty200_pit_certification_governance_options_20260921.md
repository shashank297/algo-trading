# NIFTY-200 PIT certification governance options and publication-model analysis

Date: 2026-09-21  
Repository: `shashank297/algo-trading`  
Worktree: `C:\Python projects\algo trading-authoritative-evidence`  
Branch: `codex/nifty200-pit-authoritative-evidence`  
HEAD: `b1c5bee1a7b09dff383390ad4e620f95f4a471b1`  
Local `origin/main`: `635acfcf62596c0c145f4032dde1e7020407e98e`

## Executive conclusion

The evidence demonstrates an observable archive-availability boundary at
March/April 2022, but it does not demonstrate that NSE/NSE Indices formally
discontinued NIFTY-200 monthly publication or that the files moved to a
different public product. It also demonstrates an acquisition/archive
boundary at March/April 2013, but does not prove whether 2012 files once
existed, whether monthly publication began in April 2013, or whether the
missing material is only a broken historical URL.

The formal index review model is semi-annual. The local corpus happens to
contain monthly full-roster archives from 2013-04 through 2022-03; that
observed file cadence must not be confused with the formal review cadence.

The event ledger is useful diagnostically, but is not presently sufficient
to replace the current monthly checkpoint contract: all 107 adjacent
checkpoint intervals remain non-certifiable at durable-ID level, and 16
intervals have symbol-level replay divergence. The evidence-based
recommendation is:

`INSUFFICIENT_EVIDENCE_FOR_GOVERNANCE_DECISION`

The validator and governance rules remain unchanged and validation remains
`BLOCKED`.

## 1. Current state

The current package reports:

- 597 source records: A1 590, A2 6, B1 1.
- 0 source hash failures.
- 1,544 event observations and 671 canonical events.
- 327 canonical ADD events and 344 canonical DROP events.
- 21,650 snapshot rows over 108 archived checkpoint dates.
- 58 parsed 200-member checkpoints and 50 full-roster source files with 201
  unique rows requiring count/methodology review.
- 68 monthly checkpoint blockers: 15 in 2012-01 through 2013-03 and 53 in
  2022-04 through 2026-08.
- Validation: `BLOCKED`; anchor: `NOT_ESTABLISHED`.
- Independent QA: `NOT_ASSERTED`; import approval: not granted.

The current blocker ledger was not changed by this task.

## 2. March/April 2022 publication-boundary investigation

### Local archive comparison

The structured comparison is in
`reports/nifty200_pit_publication_archive_comparison_20260921.csv`.

The four admitted A1 archives immediately before the boundary are:

| Month | NIFTY-200 member | Evidence |
| --- | --- | --- |
| 2021-12 | Yes | `NIFTY_200_Dec2021.pdf` |
| 2022-01 | Yes | `NIFTY_200_Jan2022.pdf` |
| 2022-02 | Yes | `NIFTY_200_Feb2022.pdf` |
| 2022-03 | Yes | `NIFTY_200_Mar2022.pdf` |

The 53 post-boundary candidate ZIPs from 2022-04 through 2026-08 are
byte-preserved in the existing raw cache and individually hashed in the CSV,
but were not admitted to the source catalogue by this analysis-only task.
Every one is a valid ZIP and contains other index products only. The observed
product set includes NIFTY 50, NIFTY Bank, NIFTY Financial Services, NIFTY
Midcap Select, NIFTY IT, NIFTY Next 50, and NIFTY India FPI 150. None contains
a NIFTY-200 or CNX-200 member file.

This establishes:

- a real change in the contents of the exact monthly archive pattern after
  March 2022;
- a change from a ZIP containing a NIFTY-200 member to a ZIP containing
  selected other indices;
- no proof that the NIFTY-200 historical product was discontinued;
- no proof that a separate NIFTY-200 archive was not relocated;
- no official first-party notice found in the reviewed material that explains
  the change.

The current Nifty Indices historical-data page is a selector-based historical
report facility. It exposes historical data/report categories but does not,
in the reviewed page content, provide a dated statement explaining the
March/April 2022 archive transition:
https://niftyindices.com/reports

### Boundary conclusion

March/April 2022 is a demonstrable publication-pattern boundary in the
acquired archive sequence. It is not a demonstrable formal discontinuation
boundary. The correct classification remains an evidence gap, not a
governance conclusion.

Evidence that would change this conclusion:

1. an official NSE/NSE Indices notice stating that NIFTY-200 historical
   constituent files were discontinued, relocated, or replaced;
2. an official historical-report API or archive index showing the complete
   NIFTY-200 file location for 2022-04 onward; or
3. a complete first-party NIFTY-200 roster for one or more post-boundary
   dates, with bytes and SHA-256.

## 3. 2012 to April 2013 archive-boundary investigation

The exact expected URLs for 2012-01 through 2013-03 resolve in the local
cache to the same HTML 404 response rather than ZIP bytes. The cached response
SHA-256 is:

`2e87473e6cabf210c1a9949f16dae74a8dddb2a90e3b1982f594fe31c778601d`

The response is not a valid archive and is not treated as a roster.

The first valid archive in the acquired sequence is
`indices_dataApr2013.zip`, whose NIFTY-200 member is
`cnx200_Apr2013.csv`. From May 2013 onward, the member format changes
within the ZIP sequence to PDF-based CNX/NIFTY-200 files.

The official press archive lists index-change notices during 2012 and early
2013, including the 2012 notices and the April 2013 notice, but those notices
are event assertions and not complete rosters:
https://niftyindices.com/press-release

The 2011 launch release establishes that CNX 200 launched effective July 19,
2011 and that the index review was semi-annual. Its admitted local source
hash is `b5296626fd97331ed09d0da32822434d5b1e2afd92fe035f9702ebf730b155e3`.

### Boundary conclusion

The available evidence supports only this narrower statement:

- the repository has an invalid/missing exact archive sequence through
  2013-03;
- a valid full-roster archive is available for 2013-04;
- the historical publication start date, URL migration cause, and existence
  of any other 2012 full-roster product remain unproven.

Therefore the result is category D/insufficient evidence, not a claim that
monthly publication did not exist in 2012.

## 4. Formal index review model

The first-party 2011 CNX 200 launch release states that the review is
semi-annual:
https://www.niftyindices.com/Press_Release/ind_prs18072011.pdf

The Nifty Indices review tutorial states that broad Nifty indices are reviewed
semi-annually and that the eligibility pool is prepared from data ending
January 31 and July 31:
https://niftyindices.com/resources/tutorial/review-of-indices

The current rebalancing schedule lists Nifty 200 as semi-annual, effective on
the last working day of March and September:
https://niftyindices.com/resources/index-rebalancing-schedule

These establish the formal review cadence. They do not establish a monthly
full-roster publication obligation.

The formal model also allows maintenance for corporate events and additional
replacement reviews where required. That is separate from the frequency at
which full constituent files are publicly distributed.

## 5. Complete checkpoint inventory

The canonical inventory is:

`reports/nifty200_pit_authoritative_checkpoint_inventory_20260921.csv`

It contains 109 rows:

- 108 archived full-roster checkpoint dates from 2013-04-18 through
  2022-03-31;
- one current first-party Nifty 200 page candidate, explicitly marked
  `WEB_ONLY_CURRENT_PAGE_NOT_ADMITTED` because no local constituent bytes
  or SHA-256 were admitted.

Of the 108 archived checkpoints:

- 58 have 200 unique parsed symbols;
- 50 have 201 unique parsed symbols and remain
  `FULL_ROSTER_SOURCE_COUNT_REVIEW_REQUIRED`;
- all are A1 monthly archive evidence;
- all are independent from the press/event source URLs at the source-file
  level.

The roster files do not carry durable ISINs. A diagnostic symbol-only join to
the period-valid identity master gives 17,284 unique symbol matches and 4,356
ambiguous symbol matches across 21,650 rows. This is not durable-ID
certification and is deliberately marked as non-certifiable in the inventory.

## 6. Event-sourced feasibility diagnostic

The diagnostic table is:

`reports/nifty200_pit_event_sourced_interval_reconciliation_20260921.csv`

It covers all 107 adjacent intervals between the 108 authoritative full-roster
dates.

Results:

- canonical events applied between these checkpoints: 222 ADD and 222 DROP;
- unresolved event-observation rows in the interval windows: 666. This is an
  observation count, not a claim of 666 unique events;
- durable identity completeness: NO for all 107 intervals;
- exact durable-ID set equality: NOT_CERTIFIABLE for all 107 intervals;
- symbol-level diagnostic equality: 91 intervals pass and 16 diverge;
- symbol-level divergence: 43 missing/extra member differences across the
  16 divergent intervals.

The first symbol-level divergence is the interval
2013-08-30 -> 2013-09-30:

- missing from replay: `ramcocem`;
- unexpected in replay: `madrascem`.

The symbol-level result is diagnostic only. It is not evidence that those
symbols are the same or different instruments, and it is not a license to
repair identities by fuzzy matching. The exact durable-ID comparison cannot
be certified because the historical roster rows lack ISIN and the available
identity mapping is not complete and one-to-one.

Conclusion: event-sourced reconstruction is technically useful as an
investigation tool but is not currently viable as a certification contract
replacement.

Minimum conditions for a viable event-sourced contract would be:

- authoritative starting checkpoint;
- complete A1/A2 event chain;
- exact effective dates and conservative causal `known_at`;
- period-valid durable identity for every affected security;
- no B1 dependency;
- exact reconciliation against every independent full checkpoint;
- zero unexplained HIGH/CRITICAL membership divergence;
- explicit handling of 201-member source periods;
- independent QA and versioned governance approval.

## 7. Campaign start-date analysis

### Scenario A — retain the 2012 start

Required evidence remains:

- an authoritative complete NIFTY-200/CNX-200 membership set for
  2012-01-02;
- a complete causal chain from that set to 2013-04-18;
- durable identity evidence for every affected security;
- closure of the 68 monthly checkpoint gaps under the current contract;
- certified NSE session/holiday evidence for the whole campaign range;
- resolution of duplicate events and the remaining identity blocker.

The current package has none of these conditions in a complete, validated form.
The 2012 start therefore remains blocked.

### Scenario B — first candidate certifiable checkpoint

The first available complete archive is 2013-04-18. Starting there would lose the
period from the first 2012 campaign session through 2013-04-17, approximately
15.5 months of calendar time. No Stage A, strategy research, backtest, or
trading run was performed, so this task makes no claim about whether that
period is materially required by the strategy.

Changing the start date would remove the missing initial-anchor requirement
only if the contract were explicitly scoped to begin at 2013-04-18. It would
not resolve:

- the 53 post-2022 monthly evidence gaps;
- 50 source-count reviews;
- event/identity replay divergence;
- the duplicate ABBOTINDIA and OFSS events;
- the unresolved IBULHSGFIN identity evidence;
- partial historical calendar certification.

Under the current rules, Scenario B therefore does not establish a passing
certification period.

## 8. Governance options

### Option 1 — strict monthly contract

Keep current rules unchanged.

Evidence required:

- an authoritative full NIFTY-200 roster for every required monthly
  checkpoint;
- byte-preserved source and SHA-256;
- exact durable identity;
- reconciliation and calendar gates.

Assessment: historically observed monthly files exist from 2013-04 through
2022-03, but 68 required months remain without an admissible full roster.
Free evidence may still exist, but the present searches do not establish
that it is obtainable. This option remains fail-closed.

### Option 2 — event-sourced PIT contract

Proposal only; do not implement in this task.

A replacement contract would need the minimum conditions listed in Section 6.
The current replay does not meet them, because identity completion is NO for
all intervals and 16 intervals have symbol-level divergence.

Assessment: technically conceivable, empirically unproven, and not ready for
governance approval.

### Option 3 — shorter certified research period

Use the earliest admissible full checkpoint rather than forcing a 2012 anchor.

Candidate: 2013-04-18.

Assessment: reduces the initial-anchor gap but does not remove the
post-2022 publication gap or the event/identity/calendar blockers. It is not
a passing solution under the current contract.

## 9. Recommendation

`INSUFFICIENT_EVIDENCE_FOR_GOVERNANCE_DECISION`

Do not change the validator or contract based on the observed archive
pattern. The evidence is enough to justify continued investigation and a
decision package, but not enough to prove either a formal publication
discontinuation or a complete event-sourced alternative.

The recommendation would change if the following evidence were acquired:

1. a hashable 2012-01-02 full roster or an approved, fully evidenced
   event-sourced initial state;
2. an official first-party explanation or replacement location for the
   2022-04 onward NIFTY-200 history, or complete post-2022 rosters;
3. a complete, period-valid identity linkage and exact interval reconciliation;
4. a complete authoritative NSE session/holiday corpus;
5. independent QA and explicit versioned governance approval.

## 10. Sources and hashes

No new source bytes were admitted to the PIT source catalogue in this
analysis-only task.

Existing first-party bytes relied on or inspected include:

- CNX 200 launch release, 2011-07-18:
  `b5296626fd97331ed09d0da32822434d5b1e2afd92fe035f9702ebf730b155e3`.
- 2021-12 through 2022-03 admitted monthly archives: hashes and member lists
  are in the checkpoint inventory and archive-comparison CSV.
- 2022-04 through 2026-08 candidate archive bytes: 53 individual SHA-256
  values are in the archive-comparison CSV; they remain candidate cache
  evidence and are not admitted source-catalogue records.
- 2012-01 through 2013-03 invalid HTML response:
  `2e87473e6cabf210c1a9949f16dae74a8dddb2a90e3b1982f594fe31c778601d`.

## 11. Artifacts produced

- `reports/nifty200_pit_publication_archive_comparison_20260921.csv`
- `reports/nifty200_pit_authoritative_checkpoint_inventory_20260921.csv`
- `reports/nifty200_pit_event_sourced_interval_reconciliation_20260921.csv`
- `reports/nifty200_pit_certification_governance_options_20260921.md`

The prior monthly classification report remains preserved:
`reports/nifty200_pit_monthly_checkpoint_classification_20260921.md`
and its ignored CSV remains in the worktree.

## 12. Safety and final state

- No validator or governance rule was changed.
- No source was fabricated or promoted from B1.
- No production DuckDB or WAL was touched.
- No Stage A, research, backtest, paper trading, broker API, live trading,
  push, or merge occurred.
- Current validation remains `BLOCKED`.
- Independent QA remains `NOT_ASSERTED`.
- Import approval remains not granted.

Final status:

NIFTY-200 PIT RECONSTRUCTION:  
DATA EVIDENCE BLOCKED

INDEPENDENT QA:  
NOT ASSERTED

IMPORT APPROVAL:  
NOT GRANTED

CAMPAIGN STAGE A:  
BLOCKED

