# Data Model & Contracts: Trading Dashboard

## Core Entities

The dashboard API will expose the following JSON structures:

### `StrategyRunSummary`
- `run_id`: string (UUID)
- `strategy_name`: string
- `mode`: string ("BACKTEST" or "PAPER")
- `started_at`: string (ISO 8601)
- `status`: string ("COMPLETED", "FAILED", "RUNNING")
- `total_return`: float
- `max_drawdown`: float
- `sharpe_ratio`: float
- `win_rate`: float

### `StockPerformance`
- `symbol`: string
- `pnl`: float
- `trade_count`: int
- `win_rate`: float

### `EquityCurvePoint`
- `timestamp`: string (ISO 8601)
- `equity`: float
- `drawdown`: float

### `PaperReconciliation`
- `trade_date`: string
- `expected_orders`: int
- `submitted_orders`: int
- `filled_orders`: int
- `rejected_orders`: int
- `pnl`: float
- `drift`: float

## API Contracts (FastAPI)

- `GET /api/runs`: Returns `List[StrategyRunSummary]`
- `GET /api/runs/{run_id}/equity-curve`: Returns `List[EquityCurvePoint]`
- `GET /api/runs/{run_id}/stock-performance`: Returns `List[StockPerformance]`
- `GET /api/paper/reconciliations`: Returns `List[PaperReconciliation]`
