# Codebase Research & Analysis

This document provides a comprehensive analysis of the algorithmic trading platform, highlighting responsibilities, data flows, and technical health.

## 1. Main Entry Points
- `main.py`: The primary orchestrator for the daily ingestion pipeline. It handles Angel One authentication, downloads the instrument master, fetches historical data, validates quality, and stores it in DuckDB.
- `research.py`: The CLI entry point for the backtesting and research environment. It supports multiple commands (`backtest`, `mass-research`, `paper`, `agent-research`, etc.) and handles both vectorized and event-driven modes.
- `scheduler.py`: Automates the execution of the ingestion pipeline (`main.py`) on a local cron/schedule basis.

## 2. Folder/Module Responsibilities
- `smartapi/`: Manages external integration with the Angel One broker (Auth, historical candle fetching, instrument master downloading).
- `storage/`: Owns the persistence layer, specifically `duckdb_manager.py` for idempotent upserts and schema management.
- `validators/`: Executes data-quality checks on ingested data (missing candles, duplicates, timestamp integrity, OHLC validation).
- `trading_stack/`: Contains the core research logic, strategy registry, walk-forward pipelines, cross-sectional portfolio tools, and the local `paper.py` execution simulator.
- `data_platform/`: Provider-neutral data contracts to isolate vendor-specific data models.
- `experiments/` & `orchestration/`: Manages reproducible experiment metadata, run states, and local task lifecycle.
- `ai_research/`: Houses the logic for structured OpenAI-driven research agents.
- `risk/`: Independent policy gate for conservative risk validation before any execution.
- `tools/`: Ad-hoc operational scripts for database backups, data imports, and manual backfills.
- `tests/`: A comprehensive 101-test suite covering everything from API mocking to complex walk-forward validation and data storage.

## 3. Data Flows
1. **Ingestion Flow**: 
   Angel One SmartAPI -> `smartapi.historical` -> Validation -> `storage.duckdb_manager` -> `market_data.duckdb`.
2. **Research Flow**:
   `market_data.duckdb` -> Synchronized Features -> Cross-Sectional Ranking / Single-Asset Fanout -> Vector/Event Backtest Engine -> `research_runs` table logging.

## 4. External APIs and Integrations
- **Angel One SmartAPI**: The sole external market data provider. Uses API Keys, Client Codes, PINs, and TOTP for authentication.
- **OpenAI API**: Used within `ai_research/` for LLM-assisted structural research.

## 5. Database/Storage Layer
- **DuckDB**: A single-writer local analytical database (`market_data.duckdb`). It stores the instrument master, historical candles, audit logs, quality reports, and research run metadata. 
- Schema is strictly defined in `database_schema.sql`.

## 6. Agent Architecture & Model/LLM Usage
- **AI Research (`ai_research/`)**: Uses structured, agent-based roles (e.g., Technical Analyst, Quant Analyst, Risk Analyst). 
- Agents are heavily sandboxed: they receive pre-computed evidence (walk-forward folds, RCA clusters) but have **no shell, SQL, web, or broker execution permissions**.
- **Model Usage**: LLMs (OpenAI) are used for synthesizing backtest evidence and providing research conclusions. They are restricted by explicit token/USD budgets.

## 7. Configuration and Environment Variables
- `config/config.yaml`: Contains non-sensitive configuration (rate limits, data fetch spans, timezones).
- **Environment Variables**: Strict requirement for sensitive credentials. 
  - `SMARTAPI_API_KEY`, `SMARTAPI_CLIENT_CODE`, `SMARTAPI_PIN`, `SMARTAPI_TOTP_SECRET`.
  - `OPENAI_API_KEY`.

## 8. Tests
- Extensive suite located in `tests/` with **101 tests** passing locally. 
- Fully deterministic: external broker and LLM calls are heavily mocked.
- Strong coverage (78% branch coverage) enforced by Pytest and CI workflows.

## 9. Deployment Setup
- The system is designed for **local-first** execution. There is no distributed infrastructure, no Kubernetes, and no cloud-hosted deployment.
- CI/CD exists via GitHub Actions (`.github/workflows/ci.yml`) to enforce typing (Mypy), linting (Ruff), and test passing on PRs.

## 10. Existing Coding Conventions
- Python 3.12+ syntax with strict Type Hints.
- `snake_case` for variables/functions; `PascalCase` for classes.
- Use of Loguru for structured logging instead of standard `print`.
- No strict linter enforced locally, but `ruff` and `mypy` run in CI.

## 11. Duplicated or Dead Code
- Historically, the root folder contained overlapping architectural markdown files and dead placeholders (`test.py`), which have recently been purged.
- No significant duplicated code remains, though the monolithic `tests/test_multi_strategy_platform.py` (52KB) is overly dense and handles too many overlapping test domains.

## 12. Architectural Risks
- **Single-Writer Constraint**: DuckDB locks on write. Massive parallel `mass-research` backtests logging concurrently could cause I/O locks or failures.
- **Survivorship Bias**: The platform relies on a static, current snapshot of NIFTY 200 constituents rather than point-in-time index composition.
- **Truncated Data**: Angel One minute data explicitly cuts off at 15:28 instead of 15:30.

## 13. Technical Debt
- Prices are completely **unadjusted** for corporate actions (splits, dividends), skewing long-term backtest reality.
- Missing immutable lineage (hashes) for legacy candles ingested before the latest data platform upgrade.
- Lack of independent broker sandbox/streaming data for the paper trading engine to reconcile against.

---

## Component Stability Matrix

### Stable
- **Data Ingestion (`main.py`, `smartapi/`)**: Highly stable, idempotent, and heavily tested.
- **Storage Layer (`storage/`)**: DuckDB upserts and schema management are robust and fast.
- **Validators (`validators/`)**: Quality checks run flawlessly.

### Experimental
- **AI Research (`ai_research/`)**: OpenAI integration is highly experimental, heavily sandboxed, and lacks dynamic external cost-alerting.
- **Mass Research Engine**: Multi-strategy event-driven pipelines work but lack thorough compute profiling for massive walk-forward matrices.

### Incomplete
- **Corporate Actions**: Complete lack of split/dividend adjustment capability.
- **Paper Trading Reconciliation**: `paper.py` works mathematically against the DuckDB cache, but lacks independent live-broker sandbox reconciliation.

### Unused
- **Live Trading Capabilities**: Intentionally unused/disabled. The platform cannot execute real trades and has no live routing integrations by design.
