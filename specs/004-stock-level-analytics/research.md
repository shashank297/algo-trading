# Research: Stock-Level Analytics Drilldown

## Context
The user wants to click on a specific stock within a strategy and view its isolated monthly/yearly returns and its theoretical profit as if Rs 100,000 was invested solely in that stock using that strategy.

## Unknown 1: How to calculate stock-level monthly returns?
- **Decision**: Query `trade_round_trips` filtered by `symbol` and aggregate the trade percentage returns (`net_pnl / entry_cost`) grouped by the exit month and year.
- **Rationale**: The `strategy_equity_curve` table does not have a `symbol` column, as it represents the whole portfolio. To get stock-level performance, we must derive it from individual trades. By taking `net_pnl / NULLIF(entry_cost, 0)`, we get the fractional return of each trade. We can sum these fractional returns per month to approximate the monthly return of the stock.

## Unknown 2: How to calculate the Rs 100,000 base investment profit for a specific stock?
- **Decision**: Compute the cumulative compounding return for the stock from all its trades: `Product(1 + (net_pnl / entry_cost)) - 1`. Multiply this final percentage by 100,000.
- **Rationale**: This simulates taking 100,000 Rs, investing it in the first trade, taking the proceeds (including profits/losses), and rolling it into the next trade for that specific stock. This matches the user's request of "if I invest 100,000 ... on that particular stock".

## Unknown 3: How to implement the UI drilldown?
- **Decision**: Make the rows in `StockPerformanceGrid` clickable. When clicked, it sets a `selectedSymbol` state in the parent `App.tsx` (or `AnalyticsTab.tsx`). We then pass `?symbol=...` to the analytics endpoints. If `symbol` is present, the API filters the stats, monthly returns, and ledger to only include that stock. If `symbol` is null, it shows the portfolio-level data.
- **Rationale**: Reuses the exact same layout (KPI cards, Matrix, RCA Ledger) but drills down into the specific stock, minimizing code duplication while maximizing user value.
