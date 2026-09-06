# FAB-19 Transaction Cost Reconciliation

Date: 2026-09-06  
Status: diagnostic evidence only; not a strategy approval or profitability claim.

## Method

- Source: `recovery/campaign1-20260902/base-only/market_data.duckdb`, queried read-only.
- Symbol/timeframe: `NIFTY200`, daily, 2012-10-15 through 2026-08-20; 3,429 observations and 113 trade events.
- Execution: signal from close at `t`, target applied at next-row open, mark at next-row close.
- Cost engine: `trading_stack.costs.TransactionCostCalculator`, using the date-effective Indian delivery schedule.
- Components: brokerage with min/max, buy/sell tax, exchange, regulatory, other/IPFT, side-aware fixed charge, GST, stamp duty, spread, slippage, and participation impact.
- Liquidity: impact is a capped function of participation; the calculator records participation for every order. The diagnostic uses zero participation because index-level volume is not a constituent execution-capacity proxy.
- Reproducibility: `.\venv\Scripts\python.exe tools/run_candidate_trend_backtest.py --db recovery/campaign1-20260902/base-only/market_data.duckdb --symbol NIFTY200 --window 200 --output <output.json>`

## Sensitivity evidence

| Cost scenario | Total return | Annualized return | Max drawdown | Cost drag |
|---:|---:|---:|---:|---:|
| 1.0x | 40.56% | 2.49% | -29.93% | 0.5696 |
| 1.5x | 5.46% | 0.38% | -37.00% | 0.8544 |
| 2.0x | -20.95% | -1.68% | -45.48% | 1.1392 |
| 3.0x | -55.71% | -5.71% | -61.00% | 1.7089 |

## Evidence classification and limitations

- FACT: The calculator reconciles component totals and includes fixed sell-side charges.
- FACT: Stress costs are monotonic in the recorded run: 1.0x, 1.5x, 2.0x, and 3.0x.
- FACT: The source rows are split-adjusted and provided by `angel_one`; dataset IDs and a data hash are recorded in the JSON output.
- UNKNOWN: This index series does not establish point-in-time historical constituent membership; `index_constituents_pit` is empty.
- INFERENCE: The negative 2.0x and 3.0x results show that this diagnostic is highly cost-sensitive.
- NOT CLAIMED: No strategy validation, live-trading authorization, or profitability conclusion is made.
