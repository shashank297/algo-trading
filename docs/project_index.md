# Project Index

This repository is a research-first systematic trading platform built on an Angel One SmartAPI historical-data engine.

## What the project does

- Authenticates with SmartAPI using API key, client code, PIN, and TOTP.
- Downloads and caches the instrument master.
- Fetches historical candles for configured symbols and timeframes.
- Stores data in DuckDB with idempotent upserts.
- Runs data-quality validation after ingestion.
- Writes audit logs and a run summary.

## Top-Level Files

- [main.py](../main.py): Orchestrates the entire ingestion pipeline.
- [database_schema.sql](../database_schema.sql): DuckDB schema definition.
- [README.md](../README.md): Setup, usage, and project overview.
- [requirements.txt](../requirements.txt): Python dependencies.
- [PROJECT_INDEX.md](../PROJECT_INDEX.md): This file.
- `market_data.duckdb`: Local DuckDB database generated at runtime.
- `research.py`: CLI entrypoint for research, backtesting, and paper runs.
- `scheduler.py`: Task scheduler and crontab operations.

## Configuration

- [config/config.yaml](../config/config.yaml): Active runtime config.
- [config/config.example.yaml](../config/config.example.yaml): Template config.
- [config/symbols.yaml](../config/symbols.yaml): Symbols, tokens, exchanges, and instrument types.

Important config groups:

- `smartapi`: API credentials and SmartAPI URLs.
- `database`: DuckDB file path.
- `logging`: Log directory and log settings.
- `rate_limits`: Request throttling and retry parameters.
- `data`: Start date, timeframes, instrument master refresh interval.
- `timezone`: Market timezone and market open/close times.

## Source Packages

### `smartapi/`

- [smartapi/auth.py](../smartapi/auth.py): Handles login, token refresh, header creation.
- [smartapi/historical.py](../smartapi/historical.py): Fetches and normalizes historical candles.
- [smartapi/instrument.py](../smartapi/instrument.py): Downloads, caches, and queries instrument master data.
- [smartapi/__init__.py](../smartapi/__init__.py): Re-exports SmartAPI classes.

### `storage/`

- [storage/duckdb_manager.py](../storage/duckdb_manager.py): Creates schema, upserts rows, and writes audit records.
- [storage/__init__.py](../storage/__init__.py): Re-exports the DuckDB manager.

### `validators/`

- [validators/data_quality.py](../validators/data_quality.py): Runs missing-candle, duplicate, future timestamp, null, and OHLC integrity checks.
- [validators/__init__.py](../validators/__init__.py): Re-exports the validator.

### `utils/`

- [utils/logger.py](../utils/logger.py): Loguru setup.
- [utils/report.py](../utils/report.py): Generates the run summary.
- [utils/retry.py](../utils/retry.py): Retry decorators and SmartAPI error types.
- [utils/timezone.py](../utils/timezone.py): IST helpers and date chunking.
- [utils/__init__.py](../utils/__init__.py): Re-exports utility helpers.

### `trading_stack/`

- [trading_stack/domain.py](../trading_stack/domain.py): Shared market, order, fill, and run models.
- [trading_stack/calendars.py](../trading_stack/calendars.py): Market session calendars for India, US, forex, and crypto.
- [trading_stack/features.py](../trading_stack/features.py): Research feature factory.
- [trading_stack/strategies.py](../trading_stack/strategies.py): Strategy contracts, compatibility classes, and automatic registry.
- `trading_stack/strategy_library/`: Twenty auto-discovered delivery-research strategies.
- [trading_stack/backtest.py](../trading_stack/backtest.py): Vectorized and event-driven backtest engines.
- `trading_stack/broker.py`: Broker interface and execution modeling.
- `trading_stack/paper.py`: Forward-only paper trading execution wrapper.
- [trading_stack/pipeline.py](../trading_stack/pipeline.py): End-to-end orchestration and persistence.
- [trading_stack/portfolio.py](../trading_stack/portfolio.py): Allocation helpers and authoritative cross-sectional portfolio replay.
- `trading_stack/portfolio_paper.py`: Portfolio-level paper execution coordination.
- `trading_stack/datasets.py`: Synchronized universe panels and eligibility handling.
- `trading_stack/universe.py`: Universe components and constraints processing.
- `trading_stack/costs.py`: Versioned side-aware Indian delivery costs.
- `trading_stack/rca.py`: Out-of-sample correlation, overlap, clustering, and loss attribution.
- `trading_stack/promotion.py`: Deterministic research-to-paper promotion gates.
- [trading_stack/validation.py](../trading_stack/validation.py): Chronological out-of-sample and walk-forward splits.

### Research Platform Packages

- `data_platform/`: Provider-neutral data contracts, Angel One and DuckDB adapters, optional OpenBB HTTP adapter, and provenance storage.
- `experiments/`: Reproducible experiment specifications and run management.
- `risk/`: Independent conservative risk policy and deterministic trade review.
- `orchestration/`: Persisted local task lifecycle, retry, approval, and cancellation controls.
- `ai_research/`: Structured OpenAI-first research roles with no shell, SQL, web, or broker permissions.

## Tests

- [tests/test_auth.py](../tests/test_auth.py): SmartAPI auth behavior.
- [tests/test_configuration.py](../tests/test_configuration.py): Settings and config schema.
- [tests/test_historical.py](../tests/test_historical.py): Historical data chunking, retries, and normalization.
- [tests/test_multi_strategy_platform.py](../tests/test_multi_strategy_platform.py): Core platform, orchestrations, and multi-strategy interactions.
- [tests/test_observability.py](../tests/test_observability.py): Logger and metrics assertions.
- [tests/test_operations.py](../tests/test_operations.py): Operational utility tests.
- [tests/test_quality_severity.py](../tests/test_quality_severity.py): Validation logic severity.
- [tests/test_research_platform.py](../tests/test_research_platform.py): Event loop and research tools testing.
- [tests/test_scheduler.py](../tests/test_scheduler.py): Scheduler functions and timing.
- [tests/test_storage.py](../tests/test_storage.py): DuckDB schema and upsert behavior.
- [tests/test_timezone.py](../tests/test_timezone.py): IST calculations and chunking.
- [tests/test_trading_stack.py](../tests/test_trading_stack.py): Backtest limits, risk controls, and validation runs.
- [tests/test_validators.py](../tests/test_validators.py): Data-quality checks.

## Runtime Flow

1. Load `config/config.yaml`.
2. Overlay SmartAPI secret values from environment variables.
3. Validate config and symbols.
4. Configure logging.
5. Log in to SmartAPI.
6. Initialize DuckDB and schema.
7. Download or reuse the instrument master.
8. Loop over every configured symbol and timeframe.
9. Fetch missing candle data in date chunks.
10. Upsert candles into DuckDB.
11. Write download audit logs.
12. Validate stored candles.
13. Write quality reports.
14. Generate the run summary.
15. Close the database.
16. Optionally run a strategy research or paper session via `research.py`.

## Generated Artifacts

- `logs/algotrading_YYYY-MM-DD.log`: Runtime log file.
- `logs/summary_YYYY-MM-DD.txt`: Text summary of the ingestion run.
- `data/instrument_master.json`: Cached instrument master.
- `market_data.duckdb`: Local database file.

## Notes

- See `PRODUCTION_READINESS.md` for the verified audit status, release blockers, and go-live sequence.
- See `OPERATOR_RUNBOOK.md` for preflight, backfill, research, paper, recovery, and incident procedures.
- The project is designed for local-only execution.
- Live execution remains disabled; research agents can never access SmartAPI credentials or broker actions.
- `config.yaml` and the DuckDB file should stay out of source control.

