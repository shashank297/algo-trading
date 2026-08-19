# Quickstart: Stock-Level Analytics

## Prerequisites
1. Ensure the Dashboard API and UI are running.
2. Ensure you have run at least one strategy backtest that generated trades across multiple stocks.

## Validation Steps
1. Navigate to the dashboard UI.
2. Select a Strategy Run from the `Strategy Executions` table.
3. In the `Stock-wise Attribution` grid, click on a specific stock row (e.g., INFY-EQ).
4. Verify that the UI automatically switches to the `Deep Dive Analytics` tab.
5. Verify the tab title indicates it is filtering for the specific stock (e.g., "Deep Dive Analytics (INFY-EQ)").
6. Verify the KPIs (Total Trades, Win Rate, Theoretical Profit) reflect only the trades for that stock.
7. Verify the Monthly Returns Matrix calculates returns purely based on the exit dates of the stock's trades.
8. Verify the RCA Ledger only displays entries for that specific stock symbol.
