# Feature Specification: Strategy Performance Analytics

**Feature Directory**: `specs/005-strategy-performance-analytics`
**Created**: 2026-08-19
**Status**: Ready for Planning

---

## Overview

A trader reviewing a completed backtest or live paper trading run needs a single, comprehensive analytics view for any selected strategy. Currently the Deep Dive Analytics tab shows only a minimal trade ledger and a basic monthly returns heatmap. This feature enriches that tab into a full strategy performance reporting suite so that the trader can answer — without leaving the browser — exactly how a strategy performed over any time window, whether it earns money on a Rs 1,00,000 base, and which months or years drove the outcome.

---

## Problem Statement

When a trader selects a strategy run, they can see the equity curve but cannot immediately understand:
- How many trades were executed in total, how many were profitable, how many were losers
- What the strategy earned on a standardised Rs 1,00,000 base investment
- Which calendar months and years produced the most profit or loss
- How the strategy behaved in aggregate across all years vs. a specific year (annual drill-down)
- Per-trade context: why a trade was entered, why it was exited, and whether slippage or fees consumed the edge

---

## User Scenarios & Testing

### Scenario 1 — Portfolio-level strategy overview
A trader selects **walk_forward_logistic → PORTFOLIO** from the Strategy Overview table.  
The Deep Dive Analytics tab automatically loads and shows:
- KPI cards: Total Trades, Profitable Trades, Losing Trades, Win Rate %, Total Net Profit on Rs 1,00,000 base
- A full Monthly Returns Matrix with rows = calendar years, columns = Jan–Dec; cells are colour-coded green/red by sign
- A Yearly Summary bar chart showing annual net profit in Rs for each year covered by the run
- A Trade-Level RCA Ledger with per-trade: symbol, entry date, exit date, holding days, entry price, exit price, quantity, gross PnL, fees, net PnL, entry reason, exit reason

**Acceptance**: All KPI cards show non-zero values; Monthly Matrix has no `NaN` or `e+21` style values; Yearly chart is visible and scrollable.

### Scenario 2 — Filter by year
The trader selects year **2023** from a year-selector dropdown above the Monthly Matrix.  
Only months belonging to 2023 are displayed with their individual return percentages.  
KPI cards **recalculate** to reflect only trades closed in 2023.

**Acceptance**: Selecting "2023" changes the KPI total trades count to only those trades with `exit_timestamp` in 2023.

### Scenario 3 — Stock-level analytics inside a strategy run
The trader clicks on a specific stock row in the Stock Performance Grid (e.g., **INFY-EQ**).  
The Deep Dive Analytics tab switches context to show only trades for that symbol within the selected strategy run.  
Metrics re-computed: trades for INFY-EQ only, absolute Rs profit from those trades, monthly PnL breakdown for INFY-EQ.

**Acceptance**: Stock filter banner is displayed; RCA Ledger shows only INFY-EQ rows; "Clear Filter" returns to strategy-level view.

### Scenario 4 — Paper trading run metrics
The trader selects a run with mode = **paper**.  
The same analytics view loads with identical KPIs.  
A supplementary reconciliation section lists each bar-date with expected vs. filled orders and the execution drift in Rs.

**Acceptance**: Paper run shows "Execution Drift" column in the RCA Ledger (or a separate reconciliation table).

### Scenario 5 — Overall strategy profitability on Rs 1,00,000 base
A trader wants to know: "If I had invested Rs 1,00,000 in this strategy, how much would I have today?"  
The KPI card **"Profit on Rs 1,00,000 Base"** shows the absolute rupee profit/loss.  
A secondary label shows the equivalent percentage return.

**Acceptance**: The Rs value displayed matches `total_return * 100000` for the selected run's stored metric.

---

## Functional Requirements

### FR-1: Trade Summary KPIs
- The analytics view must display these KPI cards for the selected strategy run:
  1. **Total Trades** — count of round-trip trades (entry + exit pairs)
  2. **Profitable Trades** — count with `net_pnl > 0`
  3. **Losing Trades** — count with `net_pnl <= 0`
  4. **Win Rate** — `profitable / total` as a percentage
  5. **Profit on Rs 1,00,000 Base** — absolute rupee profit scaled to a notional Rs 1,00,000 starting capital
  6. **Average Profit per Winning Trade** — average `net_pnl` for profitable trades
  7. **Average Loss per Losing Trade** — average `net_pnl` for losing trades
  8. **Profit Factor** — sum of winning PnLs divided by absolute sum of losing PnLs

### FR-2: Monthly Returns Matrix
- Rows = calendar years, columns = Jan–Dec
- Each cell shows `return_pct` formatted as a percentage with 2 decimal places
- Colour coding: green for positive, red for negative, grey for months with no trades
- No scientific notation or overflow values permitted
- Clicking a year row expands / filters to that year only

### FR-3: Yearly Returns Summary
- A bar chart with one bar per calendar year showing total net PnL in Rs for that year
- A summary row beneath the Monthly Matrix showing annual totals

### FR-4: Year Filter
- A dropdown or pill selector above the Monthly Matrix labelled "All Years | 2016 | 2017 | … | current year"
- When a year is selected, the Monthly Matrix and KPI cards recompute using only trades from that year
- "All Years" resets to full-run metrics

### FR-5: Trade-Level RCA Ledger
- A paginated table (25 rows per page) showing:
  | Column | Source |
  |---|---|
  | # | Row index |
  | Symbol | `symbol` |
  | Entry Date | `entry_timestamp` (date only) |
  | Exit Date | `exit_timestamp` (date only) |
  | Hold (days) | computed: exit - entry |
  | Entry ₹ | `entry_price` |
  | Exit ₹ | `exit_price` |
  | Qty | `quantity` |
  | Gross PnL | `net_pnl + fees + slippage` if available, else `net_pnl` |
  | Fees | `fees` |
  | Net PnL ₹ | `net_pnl` |
  | Exit Reason | `exit_reason` |
- Sortable by any column
- Colour-coded rows: green for profit, red for loss
- Exportable to CSV

### FR-6: Paper Trading Reconciliation Extension
- When the selected run has `mode = 'paper'`, display a Reconciliation section below the RCA Ledger
- Columns: Date, Expected Orders, Submitted, Filled, Rejected, PnL, Drift (Rs)

### FR-7: Persistence of Filters
- The selected year filter and stock filter must persist when switching between dashboard tabs and back
- Clearing the strategy selection resets all filters

### FR-8: Performance
- Analytics endpoints must respond in under 3 seconds for runs with up to 10,000 trades
- Monthly matrix calculation must not produce `NaN`, `Inf`, or scientific notation values

---

## Success Criteria

1. A trader can identify the best and worst calendar months for a strategy without any spreadsheet exports — everything visible in the browser
2. The "Profit on Rs 1,00,000 Base" KPI is accurate to within 1% of a manual calculation using the stored `total_return` metric
3. The RCA Ledger loads within 3 seconds for runs with up to 5,000 trades
4. All Monthly Matrix cells show human-readable percentages (no scientific notation, no NaN)
5. Year filter correctly re-scopes KPIs and the monthly matrix to only trades closed in the selected year
6. Win Rate displayed in the UI matches `profitable_trades / total_trades` to 1 decimal place

---

## Key Entities

| Entity | Description |
|---|---|
| Strategy Run | A completed backtest or paper session stored in `strategy_runs` |
| Trade Round-Trip | A paired entry+exit in `trade_round_trips` with PnL metadata |
| Monthly Return | Aggregated PnL by (year, month) derived from trade data |
| Yearly Return | Aggregated PnL by year |
| KPI Card | A summary metric displayed at the top of the analytics view |
| RCA Ledger | Paginated table of all trades with audit metadata |
| Year Filter | UI control to scope analytics to a single calendar year |

---

## Assumptions

1. All timestamps in the database are stored in IST or UTC consistently — no timezone conversion is needed at display time
2. The `trade_round_trips` table contains `fees` and `slippage` columns; if absent, Gross PnL falls back to `net_pnl`
3. Base investment of Rs 1,00,000 is a standardised display normalisation — it does not change the actual backtest capital
4. Runs with `mode = 'vectorized'` or `'event-driven'` use identical analytics KPIs; the Reconciliation section appears only for `mode = 'paper'`
5. The existing stock-level drill-down from spec 004 continues to work — this spec adds the year filter and additional KPI cards on top of that foundation

---

## Out of Scope

- Comparison between two strategy runs side-by-side
- Live order book or real-time data streaming
- Exporting the equity curve chart as an image
- Strategy parameter sensitivity analysis
