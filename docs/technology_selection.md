# Technology Selection

`pandas-market-calendars` is the maintained primary NSE schedule dependency. Local versioned
`CLOSED`, `SPECIAL_SESSION`, and `INTERRUPTION` overrides remain mandatory for exchange circulars
or special sessions not yet represented by the packaged calendar. Validation fails when data
extends beyond the configured `verified_through` boundary.

| Area | Keep | Adopt | Optional Later | Reject Now |
| --- | --- | --- | --- | --- |
| Storage | DuckDB, pandas, NumPy | Provenance tables | Parquet analytical snapshots | Replacing local storage |
| Data | Angel One SmartAPI | Provider contracts, OpenBB HTTP adapter | Dedicated US/forex/crypto providers | Mandatory OpenBB package |
| Research | Existing feature and vector engine | Causal validation, synchronized panels, quantstats reports | vectorbt only after measured bottlenecks | backtesting.py |
| Event replay | Existing broker-neutral models | Strengthened local event execution | NautilusTrader after venue decisions | Backtrader migration |
| Risk | Deterministic local policies | Independent risk gate | Advanced VaR/correlation models | LLM risk approval |
| ML | pandas, NumPy | scikit-learn and statsmodels for bounded walk-forward models | More models after validated labels | QLib, FinRL, RL stacks |
| Agents | None | Pydantic, OpenAI structured gateway | Other LLM adapters | Unrestricted autonomous agents |
| Execution | Paper broker only | Shared risk/order lifecycle | CCXT and other brokers | Live routing |

OpenBB's provider and normalized-data architecture is adopted through a small HTTP adapter, not by importing the AGPLv3 package into the core application. TradingAgents contributes evidence-bound specialized roles. Paperclip contributes task state, audit records, approval gates, and cost tracking. Awesome Systematic Trading informs the vectorized-versus-event-driven split and the deliberately small dependency set.
