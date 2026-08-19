# Feature Specification: Dashboard Analytics Deep Dive

**Feature Branch**: `003-dashboard-analytics`

**Created**: 2026-08-19

**Status**: Draft

**Input**: User description: "in the dashboard i need to check how that perticular stratigy is working momtly wise and yearly and overoll like with that perticullert stratigy how many trade is esecuted out how how manney profitable and howmany negative all that first do the detail resarsh out trading dash boadrd imp kpis rca of each backtesting trade and line paper dradiing base investment is 100000 rs how much profit that perticuler sratigy earn and all that"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Time-Series Performance Breakdown (Priority: P1)

As a quantitative trader, I want to see my strategy's performance broken down by month and year, so that I can identify seasonal weaknesses and verify consistency over time.

**Why this priority**: Essential for evaluating the long-term viability of a strategy beyond a single aggregated metric.

**Independent Test**: Can be tested by selecting a strategy and ensuring a table/chart correctly groups historical returns into monthly and yearly buckets.

**Acceptance Scenarios**:

1. **Given** a backtest covering 2 years, **When** the trader views the deep-dive analytics, **Then** they see a matrix or bar chart displaying the percentage return for each individual month and aggregated year.

---

### User Story 2 - Trade Win/Loss Analysis (Priority: P1)

As a quantitative trader, I want to see a detailed breakdown of winning versus losing trades, so that I can understand my hit rate, average win size, and average loss size.

**Why this priority**: Hit rate and reward-to-risk ratio are the most fundamental building blocks of a profitable system.

**Independent Test**: Can be tested by verifying that total trades equal the sum of profitable and negative trades, and that the profit metrics align with raw ledger data.

**Acceptance Scenarios**:

1. **Given** a strategy with 100 executed trades, **When** the trader views the analytics, **Then** they see total trades, profitable trades, and negative trades explicitly counted.
2. **Given** a base investment of Rs 100,000, **When** the trader views the profit metrics, **Then** they see the absolute currency profit (in Rs) earned by the strategy based on that notional scale.

---

### User Story 3 - Trade-Level Root Cause Analysis (RCA) (Priority: P2)

As a quantitative trader, I want to drill down into the exact ledger of individual trades with context (entry time, exit time, holding period, reason for exit), so that I can perform Root Cause Analysis (RCA) on my worst losers.

**Why this priority**: Required for debugging specific edge cases in live paper trading or historical backtesting.

**Independent Test**: Can be tested by clicking into a specific stock's ledger and viewing the chronological list of fills.

**Acceptance Scenarios**:

1. **Given** a losing trade on RELIANCE, **When** the trader clicks on the trade, **Then** they can see the exact buy price, sell price, slippage (if paper trading), and timestamp to diagnose the issue.

### Edge Cases

- What happens if a month had zero trades? It should display a 0% return for that month rather than throwing an error.
- How are open positions calculated in the Win/Loss ratio? Open positions should be excluded from the Win/Loss count until closed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST display monthly and yearly return breakdowns for a selected strategy.
- **FR-002**: System MUST calculate and display the total number of trades, number of profitable trades, and number of negative trades.
- **FR-003**: System MUST calculate absolute profit in currency (Rs) assuming a base investment of Rs 100,000.
- **FR-004**: System MUST provide a trade-level ledger view showing entry/exit prices and timestamps for RCA.

### Key Entities

- **Time-Series Returns**: Aggregated PnL grouped by month and year.
- **Trade Statistics**: Aggregate counts of wins, losses, average win, average loss.
- **Ledger Entry**: Individual buy/sell transaction linked to a specific strategy run.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The dashboard accurately categorizes 100% of trades into winning, losing, or breakeven buckets.
- **SC-002**: The absolute profit calculation accurately reflects a Rs 100,000 base scaling factor within a 0.01% margin of error.
- **SC-003**: A trader can access the specific timestamp and fill price of any historical trade in under 3 clicks from the main dashboard.

## Assumptions

- The backend DuckDB database contains sufficient granular trade-level data (`trade_round_trips` or `strategy_fills`) to calculate win/loss ratios and monthly returns.
- The base investment is fixed at Rs 100,000 for visualization purposes, even if the actual backtest used a different starting capital. (The metrics will be scaled proportionally).
