# Phase 2.5 Quickstart

Use `AssetStateService` with an existing `DuckDBManager`. The caller supplies the exact PIT universe and
authoritative benchmark. No strategy is selected.

```python
from trading_stack import AssetStateService, MarketContextType

service = AssetStateService(db)
snapshot = service.evaluate(
    symbol="RELIANCE",
    exchange="NSE",
    universe_name="NIFTY200",
    benchmark_symbol="NIFTY200",
    as_of="2026-08-28",
    decision_time="2026-08-28T15:30:00+05:30",
    context_type=MarketContextType.EOD,
    persist=True,
)
```

For INTRADAY, the same API loads certified daily evidence through D-1. Optional PIT metadata records may
be supplied explicitly; absent authoritative records produce `None` values.

