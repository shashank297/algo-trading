# Data Model & Interface Contracts: Platform Hardening

## Component Interfaces

### 1. `HistoricalDataClient` Constructor
```python
class HistoricalDataClient:
    def __init__(
        self,
        auth: SmartAPIAuth,
        config: dict[str, Any],
        rate_limiter: RateLimiter | None = None,
    ) -> None: ...
```

### 2. `InstrumentMaster.download_instrument_master`
```python
class InstrumentMaster:
    def download_instrument_master(self, force: bool = False) -> None:
        """Download or load same-day cached instrument master."""
```

### 3. `get_strategies` SQL Contract
```sql
SELECT
    sr.strategy_name,
    COUNT(DISTINCT sr.run_id) AS total_runs,
    COUNT(DISTINCT COALESCE(NULLIF(split_part(sr.run_id, ':', 2), ''), sr.symbol, 'PORTFOLIO')) AS total_stocks,
    AVG(CASE WHEN m.metric_name = 'total_return'  THEN m.metric_value END) AS avg_return,
    AVG(CASE WHEN m.metric_name = 'win_rate'      THEN m.metric_value END) AS avg_win_rate,
    AVG(CASE WHEN m.metric_name = 'sharpe'        THEN m.metric_value END) AS avg_sharpe,
    AVG(CASE WHEN m.metric_name = 'max_drawdown'  THEN m.metric_value END) AS avg_max_drawdown,
    AVG(CASE WHEN m.metric_name = 'profit_factor' THEN m.metric_value END) AS avg_profit_factor
FROM strategy_runs sr
LEFT JOIN strategy_metrics m ON sr.run_id = m.run_id
GROUP BY sr.strategy_name
ORDER BY total_runs DESC, avg_return DESC
```
