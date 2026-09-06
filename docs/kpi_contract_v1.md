# Canonical KPI contract v1

`trading_stack.kpi` is the provider-neutral KPI contract for backtest and paper
reports. The serialized `schema_version` is `1.0.0`; consumers must reject an
unknown major version rather than silently reinterpret fields.

## Evidence and units

Every metric contains `value`, `unit`, `window`, `annualization_factor`,
`status`, and `basis`. `window=full_sample` means all supplied observations;
there is no implicit rolling window. Returns, volatility, Sharpe, Sortino,
drawdown, hit rate, and exposure are decimal fractions (`0.10` means 10%).
Currency metrics use the report's stated base currency. Counts are integer
counts. Turnover is the sum of filled notional, not a percentage.

`annualization_factor` is the number of observations per year supplied by the
caller (for example, 252 for Indian daily sessions). CAGR uses
`(ending/starting) ** (1 / (observations / factor)) - 1`. Volatility is
population standard deviation of period returns multiplied by the square root
of the factor. Sharpe is mean divided by population standard deviation,
annualized by the square root of the factor, with an implicit zero risk-free
rate. Sortino uses only negative period returns as the downside sample.

## Definitions

| Key | Definition | Basis |
| --- | --- | --- |
| `net.total_return` / `gross.total_return` | Ending equity divided by starting equity minus one | Net marked equity / gross marked equity |
| `net.cagr` / `gross.cagr` | Annualized compound return over the full sample | Equity curve and declared factor |
| `net.volatility` / `gross.volatility` | Annualized period-return volatility | Population standard deviation |
| `net.sharpe` / `gross.sharpe` | Annualized excess-return-to-volatility ratio | Zero risk-free rate; no risk-free series is inferred |
| `net.sortino` / `gross.sortino` | Annualized mean return divided by downside deviation | Negative period returns only |
| `net.max_drawdown` / `gross.max_drawdown` | Minimum peak-to-trough equity decline | Running equity peak |
| `trades.count` | Number of completed trades | Caller-provided completed trade P&Ls |
| `trades.hit_rate` | Positive completed trades divided by completed trades | No break-even wins |
| `turnover.notional` | Sum of filled notional | Currency; both buy and sell legs as supplied |
| `exposure.gross_mean` | Mean absolute gross exposure as fraction of equity | Caller-provided point-in-time exposure |
| `costs.total` | Sum of explicitly supplied cost components | Fees, slippage, taxes, and other declared costs |
| `capacity.max_participation` | Maximum supported volume participation | Requires point-in-time liquidity evidence; unavailable in v1 calculator |
| `liquidity.median_daily_value` | Median point-in-time daily traded value | Requires certified volume data; unavailable in v1 calculator |
| `uncertainty.return_ci_95` | 95% interval for return | Requires a declared resampling method; unavailable in v1 calculator |

Unavailable or mathematically undefined metrics are serialized as `value: null`
with `status: "unavailable"`. `0.0` is reserved for a measured zero, never for
missing data. A report is not profitability evidence by itself: callers must
also include data lineage, point-in-time certification, execution assumptions,
cost schedule, and reproducibility identifiers.

## Reproducibility

Use `calculate_canonical_kpis` with causal period-level inputs, an explicit
frequency, and an explicit annualization factor. Serialize with `to_json()`;
the output is key-sorted and uses compact separators. The compatibility tests
in `tests/test_kpi_contract.py` are deterministic and cover gross/net
separation, units, missing-value semantics, and round-trip stability.
