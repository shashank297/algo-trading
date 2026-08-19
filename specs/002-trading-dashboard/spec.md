# Feature Specification: Trading Dashboard

**Feature Branch**: `002-trading-dashboard`

**Created**: 2026-08-19

**Status**: Draft

**Input**: User description: "build me a complte fullflage dashboard in which i can see the stock wise and stratigy wise backtesting KPIs and paper trading make it prodection redy build it soppose you are the trader devloper with 24 year of expriance"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Strategy KPI Monitoring (Priority: P1)

As a quantitative trader, I want to view high-level performance metrics for all my backtested and paper-traded strategies so that I can quickly identify which strategies are profitable and performing within expected risk boundaries.

**Why this priority**: Core value of the dashboard is visibility into the automated strategies' aggregate performance.

**Independent Test**: Can be fully tested by loading the dashboard and verifying that aggregate backtest and paper trade metrics (e.g., total return, max drawdown, Sharpe ratio) match the underlying historical run data.

**Acceptance Scenarios**:

1. **Given** several completed strategy backtests and paper trades in the database, **When** the trader opens the dashboard's strategy overview, **Then** they see a table summarizing KPIs for each strategy variant.
2. **Given** a selected strategy, **When** the trader clicks on it, **Then** they see detailed time-series charts (equity curve, drawdowns) for that strategy.

---

### User Story 2 - Stock-level Performance Drill-down (Priority: P1)

As a quantitative trader, I want to drill down into stock-wise execution metrics so I can understand if my alpha is being driven by a few outliers or is robust across the universe.

**Why this priority**: Essential for identifying the source of strategy PnL and evaluating stock selection efficacy.

**Independent Test**: Can be tested by selecting a specific instrument in the dashboard and verifying that the win rate, PnL, and trade count match the underlying ledger for that stock.

**Acceptance Scenarios**:

1. **Given** a strategy that trades a universe of 50 stocks, **When** the trader navigates to the stock performance view, **Then** they see a breakdown of PnL, Win Rate, and Total Trades grouped by stock ticker.
2. **Given** the stock view, **When** the trader sorts by worst-performing stocks, **Then** the list is accurately sorted to show the largest losers first.

---

### User Story 3 - Paper Trading Reconciliations (Priority: P2)

As a quantitative trader, I want to monitor the health and slippage of my live paper trading sessions so I can ensure the models transition safely from backtest to production.

**Why this priority**: Crucial for operational monitoring, but strategy KPIs are theoretically more foundational.

**Independent Test**: Can be tested by viewing the paper trading dashboard tab and verifying order fill rates and slippage metrics.

**Acceptance Scenarios**:

1. **Given** active paper trading sessions with recorded reconciliations, **When** the trader visits the paper trading monitor, **Then** they see expected vs. submitted orders, rejection counts, and calculated drift.

### Edge Cases

- What happens if the database contains no completed strategy runs or trades? The dashboard should display a user-friendly empty state with instructions on how to run a backtest.
- How does the system handle corrupted or missing data (e.g., missing equity curve points)? It should gracefully interpolate or skip the points and display a warning banner.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST display an aggregated overview of strategy-level KPIs (Total Return, Max Drawdown, Sharpe Ratio, Win Rate).
- **FR-002**: System MUST display a stock-level breakdown of performance (PnL, Trade Count, Win Rate per symbol).
- **FR-003**: System MUST display paper trading health metrics including order fill rates, rejected orders, and execution slippage/drift.
- **FR-004**: System MUST allow filtering of data by date range, strategy name, and execution mode (backtest vs. paper).
- **FR-005**: System MUST provide interactive visualizations, specifically an equity curve and underwater (drawdown) chart over time.
- **FR-006**: System MUST securely read from the local data store without mutating existing market or trade data.

### Key Entities

- **Strategy Run**: Represents an execution session of a specific strategy (backtest or paper). Contains aggregate metrics.
- **Trade Execution**: Represents individual stock-level fills and orders that generate the stock-level KPIs.
- **Equity Curve Observation**: Time-series data points representing the portfolio value over time.
- **Paper Reconciliation**: Daily operational health records comparing expected orders to broker fills.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Traders can identify their best and worst performing strategies in under 15 seconds from launching the dashboard.
- **SC-002**: Dashboard loads and renders all primary KPI tables and charts in under 2 seconds for databases containing up to 10,000 trades.
- **SC-003**: The dashboard does not execute any write operations to the historical trade databases, ensuring 100% data integrity.
- **SC-004**: Traders can isolate the exact PnL attribution of a single stock within 3 clicks.

## Assumptions

- The trading system stores its backtest and paper trading history in a structured SQL-compliant database (DuckDB) that can be queried by the dashboard.
- The dashboard is intended for local or internal network deployment (single-tenant trader), not for public multi-tenant SaaS access.
- Existing metrics (Sharpe, Drawdown) are pre-calculated by the trading engine or can be easily aggregated via standard SQL queries over the equity curve.
- The user requires a modern, responsive web-based UI rather than a CLI or static report.
