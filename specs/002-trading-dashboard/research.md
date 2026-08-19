# Research: Trading Dashboard

## Dashboard Technology Stack

**Decision**: Vite + React (TypeScript) for Frontend, FastAPI for Backend.
**Rationale**: The user requested a "complete full-fledged dashboard" that is "production ready". The agent guidelines mandate "Rich Aesthetics", "smooth gradients", "micro-animations", and "Prioritize Visual Excellence" which is difficult to achieve purely with Streamlit or Dash. A decoupled architecture with a Python FastAPI querying DuckDB and serving a Vite React SPA provides the best control over the UI, enabling high-performance charts and premium design.
**Alternatives considered**: 
- *Streamlit*: Fast to build, but lacks fine-grained CSS control and micro-animations required for a "wow" factor.
- *Dash*: Better than Streamlit for complex layouts, but still restrictive compared to a raw React app.

## Database Queries & Integration

**Decision**: The FastAPI backend will use DuckDB's Python client in read-only mode to fetch metrics.
**Rationale**: DuckDB allows concurrent readers or a single writer. The `trading_stack` may be writing (during backtests or paper trading). The dashboard API must connect with `read_only=True` to avoid `duckdb.IOException` locks when a backtest is concurrently running.
**Tables to query**:
- `strategy_runs`: To list available runs and their status.
- `strategy_metrics`: To get aggregate KPIs (Total Return, Sharpe, Max Drawdown).
- `strategy_fills` and `portfolio_positions`: To aggregate stock-wise PnL, win rate, and trades.
- `strategy_equity_curve`: For the main portfolio value chart.
- `paper_reconciliation`: For paper trading health.

## Charting Library

**Decision**: Lightweight charting using Recharts or Chart.js wrapped in React.
**Rationale**: Need performant time-series rendering for equity curves without heavy dependencies. Recharts is React-native, customizable, and supports tooltips and gradients out of the box, aligning with the premium aesthetic requirement.
