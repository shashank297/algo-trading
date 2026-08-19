# Data Model & Contracts: Stock-Level Analytics

## API Contracts Updates

The existing analytics endpoints will be updated to accept an optional `symbol` query parameter.

- `GET /api/runs/{run_id}/analytics/stats?symbol={symbol}`
  - If `symbol` is provided, calculates `total_trades`, `winning_trades`, `losing_trades`, and `win_rate` filtering `trade_round_trips` by the symbol.
  - Calculates `base_investment_profit` by finding the cumulative compounded return of all trades for that symbol, multiplied by 100,000.

- `GET /api/runs/{run_id}/analytics/monthly?symbol={symbol}`
  - If `symbol` is provided, aggregates `trade_round_trips` by `exit_timestamp` year and month. The `return_pct` is the sum of `(net_pnl / entry_cost)` for trades closed in that month.

- `GET /api/runs/{run_id}/analytics/ledger?symbol={symbol}`
  - If `symbol` is provided, filters the returned `trade_round_trips` rows for the RCA ledger to only include that specific symbol.
