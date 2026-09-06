# FAB-30 — NIFTY 200 historical PIT provider confirmation and sample request

**Date:** 2026-09-06 (Asia/Kolkata)  
**Project:** Algo Trading — Research, Backtesting & Paper Trading (`bc59843d-1e91-4232-af11-19d37b952301`)  
**Requested horizon:** 2012-01-02 through 2026-08-20, inclusive  
**Disposition:** BLOCKED pending written provider confirmation and CEO/Board data-route approval

## Executive finding

The only provider capability confirmed from authoritative public material is that **NSE Indices
offers ongoing and historical index data by subscription**, including constituent data with company
names, identifiers, market capitalisation, weights, and prices, and explicitly lists quantitative
research as a use case. The page does **not** confirm that the requested NIFTY 200 history is
point-in-time, includes knowledge/publication timestamps, contains complete historical membership
events, or includes historical identity/listing/status and liquidity fields. Therefore no provider
is yet certified for this research objective.

NSE Data & Analytics separately advertises EOD/historical, corporate, and other market-data products,
but its public page likewise does not establish a PIT constituent/event product for NIFTY 200. These
are leads for a written sales/data inquiry, not admissible PIT evidence.

## Evidence classification

- **FACT:** NSE Indices describes ongoing and historical index products and says constituent data
  includes names, identifiers, market capitalisation, weights, and prices.
- **FACT:** NSE Indices provides a subscription contact: `indices@nse.co.in`.
- **FACT:** The official NIFTY 200 page describes the index as the combination of NIFTY 100 and
  NIFTY Midcap 100 and links current constituent, factsheet, and methodology downloads.
- **FACT:** Existing local FAB-26/FAB-27 evidence found no complete, independently reconciled,
  first-party PIT ledger for the required horizon.
- **INFERENCE:** NSE Indices is the highest-priority provider to query because it is the index
  administrator and publicly advertises historical constituent data; capability still requires
  confirmation of PIT semantics and field-level coverage.
- **UNKNOWN:** Whether a licensed extract can provide all historical membership events, announcement
  timestamps, effective dates, ISIN continuity, listing/suspension/delisting status, and the exact
  pre-decision six-month liquidity inputs for every review in 2012–2026.
- **ASSUMPTION:** A provider response or sample may be evaluated for research feasibility, but may
  not be promoted into the canonical dataset until licensing, provenance, PIT, replay, and
  Independent QA/Risk gates pass.

## Minimum acceptance criteria for a provider sample

Request a machine-readable sample covering at least these slices: one early review (`2012-01-02`
through `2013-12-31`), one middle review (`2018-01-01` through `2020-12-31`), and one recent review
(`2024-01-01` through `2026-08-20`). The sample must include, per membership/event row:

1. `index_code`, `isin`, `symbol_at_event`, security name, exchange, and instrument type;
2. `announcement_at`/publication timestamp with timezone and `effective_from`/`effective_to`;
3. event type plus additions, removals, and unchanged members at each rebalance;
4. listing, suspension, delisting, merger/demerger, and symbol-change status with source lineage;
5. the exact pre-decision liquidity inputs, window definition, cut-off date, units, and missingness;
6. weights, prices, shares/free-float fields if used to construct the index;
7. immutable source identifiers/URLs, retrieval or vendor-ingestion timestamps, file version,
   row-level or batch hashes, and a data dictionary;
8. adjustment semantics for prices/volumes and a statement that no current constituents were
   backfilled into earlier dates;
9. delivery format, pagination/partitioning, corrections policy, historical restatement policy,
   retention, redistribution rights, and a reproducible checksum-bearing sample file.

A sample fails closed if it has only current constituents, event effective dates without knowledge
timestamps, symbol-only identity, unexplained gaps, undocumented restatements, or no source lineage.

## Draft provider request

**Subject:** Request for NIFTY 200 historical point-in-time constituent/PIT data sample (2012–2026)

> We are evaluating a licensed historical-data source for quantitative research on the NIFTY 200
> over 2012-01-02 through 2026-08-20 (inclusive). Please confirm whether you can provide a
> point-in-time, survivorship-bias-controlled history of the index constituents and the inputs
> needed to reproduce membership at each decision date.
>
> Please send a non-production sample for three slices: 2012-01-02–2013-12-31, 2018-01-01–2020-12-31,
> and 2024-01-01–2026-08-20. For each row/event, please include index code, ISIN, historical symbol,
> security name, exchange/instrument type, announcement/publication timestamp with timezone,
> effective dates, event type, additions/removals/unchanged members, historical status events,
> liquidity-window inputs and definitions, weights/prices/free-float fields, source lineage,
> retrieval/version metadata, and checksums. Please state whether data are restated, how corrections
> are communicated, and whether the extract is reproducible as delivered.
>
> Please also provide the data dictionary, coverage/gap report, adjustment methodology, API or bulk
> delivery specification, licence/redistribution terms, indicative pricing, and confirmation that
> no current constituent list is projected backward. We will not use the sample for trading or claim
> research validity before independent PIT and QA/Risk review.

## Decision and next action

This report is a provider-feasibility artefact only; no external request was sent and no paid-data
purchase was authorized. CEO/Chief of Staff must authorize the provider inquiry and, separately,
the Board must approve any licensed-data route. On receipt, Research + Engineering should hash and
retain the untouched sample, map it to the existing PIT contract, and submit a gap matrix to
Independent QA/Risk. FAB-17, FAB-26, and FAB-27 remain blocked until that review succeeds.

## Reproducibility

Local evidence reviewed:

- `reports/FAB-26_nifty200_pit_evidence_20260906.md`
- `reports/FAB-27_zero_cost_nse_pit_liquid_equity_certification_20260906.md`
- `reports/FAB-27_qa_risk_review_20260906.md`
- `reports/FAB-28_board_decision_pack_20260906.md`

Authoritative provider references checked 2026-09-06:

- https://www.nseindia.com/static/nse-indices/index-data-subscription
- https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-200
- https://nseindia.in/static/nse-data-and-analytics/data-information-vending
