# Paperclip handoff

Use this package only as a sibling foundation/evidence input for FAB-27.

Current required horizon: 2012-01-02 through 2026-08-20.

Governance:
- FAB-17 remains BLOCKED.
- `NIFTY200_HISTORICAL_PIT_DATA` remains `resolved: false`.
- This package must not automatically reopen FAB-17 or replace it.
- Independent QA/Risk must review any completed reconstruction.
- Do not repair or mutate `market_data.duckdb` or `market_data.duckdb.wal`.
- Do not run strategy/backtest/paper/broker/live workflows.

Recommended follow-up: Independent QA/Risk review of the FAB-27 evidence bundle.

Agent sequence:
1. Research & Intelligence Lead: source discovery and evidence inventory.
2. Engineering & Automation Lead: run acquisition/extraction in a clean evidence path.
3. Research + Engineering: normalize events and reconcile official snapshots.
4. Independent QA/Risk: fail-closed review.
5. Stop for Board review.

Acceptance: use `reports/FAB-27_zero-cost_nse_pit_liquid_equity_certification_20260906.md`.
The current disposition is `BLOCKED`; do not emit `CANDIDATE_ACCEPTABLE_FOR_BOARD_REVIEW` until
coverage, identity, liquidity, reconciliation, reproducibility, and Independent QA/Risk review
are complete.

Do not mark FAB-17 PASS from this package alone.
