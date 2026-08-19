<!--
SYNC IMPACT REPORT
Version: Initial Draft -> 1.0.0
Modified Principles:
- Added I. Data Integrity & Validation
- Added II. Event-Driven Execution
- Added III. Concurrency & Thread Safety
- Added IV. DuckDB Resiliency
- Added V. Cost Accuracy & Risk Limits
Added Sections:
- Security & Data Safety
- Testing Guidelines
-->
# Algo Trading Platform Constitution

## Core Principles

### I. Data Integrity & Validation
Never silently swallow bad data. Invalid canonical candles (e.g., mathematically impossible `high < low` anomalies from pre-market auctions) must be gracefully dropped with a warning, ensuring the mass-research pipeline continues uninterrupted for valid data.

### II. Event-Driven Execution
All strategy simulations must strictly use the `EventDrivenBacktester`. Vectorized backtesting is strictly prohibited for production evaluation to categorically prevent lookahead bias and ensure 1:1 parity with live paper trading.

### III. Concurrency & Thread Safety
All external API interactions (especially Angel One authentication and token refreshing) MUST be synchronized using `threading.Lock`. The system heavily leverages `ThreadPoolExecutor` (up to 64 cores); unprotected network calls will result in broker-side rate limit bans or `AG8001 - Invalid Token` errors.

### IV. DuckDB Resiliency
DuckDB enforces a strict single-writer file lock. 
1. The Dashboard API (and any other readers) MUST connect with `read_only=True`.
2. All pipeline writers MUST implement a retry/backoff loop when calling `duckdb.connect()` to survive transient locks held by concurrent readers.

### V. Cost Accuracy & Risk Limits
Every backtest MUST apply the `IndianDeliveryCostSchedule` (or appropriate derivative model). Raw PnL reporting without accounting for slippage, broker fees, and statutory taxes is strictly forbidden. 

## Security & Data Safety

- **Secrets**: Never commit `config/config.yaml`, API keys, TOTP secrets, broker tokens, `.duckdb` database files, or runtime logs. Use environment variables as documented in `config.example.yaml`.
- **Live Routing**: Live order routing must remain disabled unless explicitly overriden via the safety switch.
- **Data Fabrication**: Never fabricate pre-listing prices or silently mix split-adjusted and unadjusted datasets in the same fold.

## Testing Guidelines

Tests use `pytest` and files follow `tests/test_*.py`. 
- Add deterministic tests for every behavioral change, especially next-bar execution, timezone/calendar handling, costs, risk limits, and persistence. 
- Mock all broker and LLM calls; tests must NEVER require live network access or real credentials to pass.

## Governance

This Constitution supersedes all other practices. All automated generation, refactoring, and PR reviews must verify compliance against these principles. 

**Version**: 1.0.0 | **Ratified**: 2026-08-20 | **Last Amended**: 2026-08-20
