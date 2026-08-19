# Data Model & Contracts: Dashboard Analytics

## Core Entities

### `TradeStats`
- `total_trades`: int
- `winning_trades`: int
- `losing_trades`: int
- `win_rate`: float
- `base_investment_profit`: float

### `MonthlyReturn`
- `year`: int
- `month`: int
- `return_pct`: float

### `TradeLedgerEntry`
- `trade_id`: string
- `symbol`: string
- `entry_timestamp`: string
- `exit_timestamp`: string
- `quantity`: float
- `entry_price`: float
- `exit_price`: float
- `net_pnl`: float
- `entry_reason`: string
- `exit_reason`: string

## API Contracts (FastAPI)

- `GET /api/runs/{run_id}/analytics/stats`: Returns `TradeStats`
- `GET /api/runs/{run_id}/analytics/monthly`: Returns `List[MonthlyReturn]`
- `GET /api/runs/{run_id}/analytics/ledger`: Returns `List[TradeLedgerEntry]`
