# Research: Dashboard Analytics

## Calculation of Monthly/Yearly Returns

**Decision**: Aggregate `strategy_equity_curve` points to compute time-series returns.
**Rationale**: The `strategy_equity_curve` has the portfolio `equity` at each `timestamp`. We can group by year/month and take `(last_equity / first_equity) - 1` to find the exact percentage return for that period.
**Alternatives**: Using `trade_round_trips` to sum PnL per month. However, overlapping holding periods and unrealized PnL make trade-based returns less accurate than equity curve snapshots.

## Trade Win/Loss and RCA Ledger

**Decision**: Query the `trade_round_trips` table to get exact trade stats.
**Rationale**: It contains `net_pnl`, `entry_timestamp`, `exit_timestamp`, `entry_price`, `exit_price`, and reasons.
- `Total Trades = count(*)`
- `Winning Trades = sum(net_pnl > 0)`
- `Losing Trades = sum(net_pnl < 0)`
- The ledger view will simply return the rows of this table for the RCA grid.

## Base Investment Normalization

**Decision**: Calculate the final absolute profit by taking the cumulative percentage return of the strategy and multiplying by Rs 100,000.
**Rationale**: The original strategy might have been simulated with $10,000 or $1M. By taking the `net_return` percentage metric and scaling it by the requested 100,000 base, we provide a normalized absolute PnL value for comparison as requested by the user.
