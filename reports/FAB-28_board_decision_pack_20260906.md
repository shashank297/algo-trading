# FAB-28 — Board decision pack: certifiable zero-cost universe and horizon

**Date:** 2026-09-06 (Asia/Kolkata)  
**Project:** Algo Trading — Research, Backtesting & Paper Trading (`bc59843d-1e91-4232-af11-19d37b952301`)  
**Scope:** decision pack only; paper trading remains the sole permitted mode.

## Executive decision requested

Approve one explicitly named path below. The approved objective remains **2012-01-02 through 2026-08-20** unless the Board explicitly approves a shortened alternative. No current constituent list may be projected backward, and no strategy, backtest, paper session, broker, credential, order, live endpoint, or capital deployment is authorized by this pack.

## Evidence available now

Facts observed in the retained local evidence:

- `reports/FAB-26_nifty200_pit_evidence_20260906.md` records the requested NIFTY 200 horizon as blocked: no complete dated first-party membership/event archive was demonstrated.
- The raw public-source directory contains **358 files** and `source_manifest.csv` contains **357 hashed rows** (the independent QA/Risk report records these counts). These are discovery/input artifacts, not a certified PIT ledger.
- The extraction summary records **247** press-release files scanned, **98** containing NIFTY 200 text, and **one** monthly candidate record; disposition is `BLOCKED` because event normalization and independent reconciliation are incomplete.
- Monthly checkpoint and press-release coverage seeds remain `UNRESOLVED_GAP` across 2012-01-02–2026-08-20. The candidate package has no complete, independently reconciled ISIN identity, listing/status, turnover, and rebalance evidence.
- Independent QA/Risk recorded **FAIL**. The deterministic test command passed 3 tests, but adversarial validation exposed exception/malformed-metadata failures; QA also identified a manifest path-base replay constraint.

## Coverage and earliest certifiable horizon

| Question | Current answer | Classification |
|---|---|---|
| Exact free-data corpus currently retained | 358 files / 357 manifest rows; 247 press-release files scanned, 98 NIFTY 200 candidates | Fact |
| Fully certified PIT horizon | None | Fact / fail-closed disposition |
| Earliest date that can be certified today | Not established; no interval is certified | Fact |
| Why not infer a shortened horizon? | Gaps include identity, listing/status, turnover completeness, effective dates, and reconciliation; recent years are also marked unresolved | Fact |
| Approved objective | 2012-01-02 through 2026-08-20 | Board constraint |

The phrase “shortened zero-cost alternative” therefore means a **new Board-approved scope**, not a claim that any particular shortened dates are already certified. A shortened horizon must still pass the same PIT, identity, liquidity, replay, and Independent QA/Risk gates.

## Options

| Option | Scope | Benefits | Cost / risk | Current status |
|---|---|---|---|---|
| A — Preserve full objective | 2012-01-02–2026-08-20; continue first-party evidence recovery and reconciliation | Retains approved research question and maximum history | Longest evidence effort; currently blocked | Recommended default |
| B — Shortened zero-cost pilot | Board chooses explicit start/end dates after a feasibility check; no certification implied in advance | May reduce unresolved historical work and produce a bounded research candidate | Could still fail; shorter history reduces statistical power and must not be presented as full-horizon evidence | Requires Board approval and a fresh evidence/QA task |
| C — Licensed/paid exact-data route | Vendor-supplied PIT constituents, identity/status, corporate actions, and historical liquidity, with redistribution/licence terms reviewed | Potentially closes the archive and identity gaps fastest | Budget, licence, provenance, and vendor-quality risks; paid-data approval required | Requires Board approval; no procurement authorized |
| D — Current snapshot only | Current NIFTY 200 members projected backward | Fastest operationally | Survivorship/look-ahead contamination; expressly prohibited for PIT research | Reject |

## Recommendation

**Recommend Option A as the governing decision:** retain the full approved horizon and commission only the minimum evidence-recovery/reconciliation work needed to determine whether it can be certified. In parallel, the Board may approve Option B as a separately labeled pilot, but should not select dates based on an unsupported assumption that 2021 onward (or any other interval) is already certifiable. Option C is a Board-level budget/licence decision and should be evaluated only if zero-cost recovery cannot close the named gaps. Reject Option D.

## Required Board decision

The Board should record:

1. `APPROVE_FULL_HORIZON` for 2012-01-02–2026-08-20, or `APPROVE_SHORTENED_HORIZON` with exact inclusive dates; and
2. whether to authorize a licensed/paid-data feasibility proposal (budget and licence review), or keep the work zero-cost only.

Until that decision and subsequent Independent QA/Risk acceptance, the research-universe status remains `BLOCKED`; no strategy result is valid on this unresolved universe.

## Acceptance / ownership

- **Deliverable:** this decision pack plus the retained FAB-26/FAB-27 evidence reports.
- **Accountable owner:** AI Studio CEO / Chief of Staff for Board decision capture.
- **Next execution owner if approved:** Research & Engineering for evidence recovery and reconciliation.
- **Independent reviewer:** Independent QA / Risk Lead.
- **Definition of done:** Board decision recorded with exact dates and data-source route; evidence bundle is reproducibly replayed; identity/listing/status/liquidity/rebalance controls pass; Independent QA/Risk signs off; only then may the universe enter research.
- **Dependencies:** Board scope/data-route decision; first-party source completeness or an approved licensed source; no database/WAL mutation.

## Evidence links

- `reports/FAB-26_nifty200_pit_evidence_20260906.md`
- `reports/FAB-27_zero-cost_nse_pit_liquid_equity_certification_20260906.md`
- `reports/FAB-27_qa_risk_review_20260906.md`
- `reports/nifty200_zero_cost_pit_extraction_summary.json`
- `data/raw/nifty200_pit_public_sources/source_manifest.csv`
