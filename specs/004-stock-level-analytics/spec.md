# Feature Specification: Stock-Level Analytics Drilldown

**Feature Branch**: `004-stock-level-analytics`

## User Scenarios

### User Story 1 - Drilldown from Strategy to Stock
As a trader, when I click on a specific stock in the `StockPerformanceGrid`, I want to navigate into a specialized drilldown view for that exact stock, so I can see its performance isolated from the rest of the portfolio.

### User Story 2 - Stock-Specific Time-Series and Base Profit
As a trader, in the stock drilldown view, I want to see the monthly/yearly returns and the Rs 100,000 base investment profit exclusively for that stock.

## Requirements
- The UI must allow clicking on a row in `StockPerformanceGrid` to enter stock-level analytics.
- The `AnalyticsTab` (or a dedicated component) must support fetching analytics filtered by `symbol`.
- The APIs (`/api/runs/{run_id}/analytics/*`) must accept an optional `?symbol=XYZ` query parameter and filter the database queries appropriately.
- If filtering by symbol, `strategy_equity_curve` cannot be used for time-series returns since it is aggregated at the portfolio level. Time-series returns for a specific stock must be calculated from `trade_round_trips` directly, or a stock-level equity curve if it exists.
