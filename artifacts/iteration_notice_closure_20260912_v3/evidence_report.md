# NIFTY-200 PIT public evidence build

## Scope and safety

This build covers 2012-01-02 through 2026-08-20. It parses cached official NSE/Nifty Indices evidence and a separately labelled non-authoritative B1 public reconstruction challenger; it does not alter `market_data.duckdb`, import authoritative rows, start Stage A, or enable trading. Independent QA remains `NOT_ASSERTED`.

## Evidence sources

- [Nifty 200 official index page](https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-200)
- [Nifty Indices reports](https://www.niftyindices.com/reports)
- [Monthly reports](https://niftyindices.com/reports/monthly-reports)
- [Nifty rebalancing schedule](https://www.niftyindices.com/resources/index-rebalancing-schedule)
- [NSE equity market-data downloads](https://www.nseindia.com/static/products-services/equity-market-data-reports-download)

- [B1 challenger event reconstruction](https://github.com/deshpanda/nse-screener-data/blob/main/reconstitution/events.parquet)

## Results

- Source records: 373; source hash errors: 0.
- Source tiers: A1=369, B1=1.
- Event observations: 1484; canonical events: 630.
- Monthly snapshot rows: 21650 across 108 checkpoints.
- Durable identity mappings: 4032 certified; 0 remain manual-review candidates.
- Coverage gaps or non-200 checkpoints: 68 campaign months.
- NSE sessions checked: 3609; replay count range: 0..133.
- Blocker ledger rows: 3844; known_at unresolved canonical events: 0.
- Automated validation: **BLOCKED**.

The package is intentionally blocked because the available evidence does not yet provide a complete, causally timestamped, durable-identity reconstruction for every campaign day. No synthetic initial membership or fabricated ISIN was created.
