# Quickstart: Dashboard Analytics Deep Dive

## Prerequisites

1. Ensure `market_data.duckdb` has `trade_round_trips` data available.
2. The dashboard API and UI must be running.

## Local Validation

1. Open `http://localhost:5173`
2. Select a Strategy Run from the Overview Table.
3. Assert that the "Analytics" tab appears.
4. Verify the Monthly/Yearly returns matrix is populated.
5. Verify the Trade Win/Loss breakdown is visible and total profit is scaled to a Rs 100,000 base.
6. Scroll down to the RCA Ledger and verify individual trades have entry/exit timestamps and exact prices.
