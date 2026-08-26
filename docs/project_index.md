# Project Index

This repository is a research-first systematic trading and simulation platform built on an Angel One SmartAPI historical-data and streaming engine.

## What the project does

- Authenticates with SmartAPI using API key, client code, PIN, and TOTP.
- Downloads and caches the instrument master.
- Fetches historical candles for configured symbols and timeframes with rate limiting and retry backoff.
- Ingests live binary WebSocket packets, decodes feeds, tracks sequence gaps, and logs telemetry.
- Computes canonical `SPLIT_ADJUSTED` price data using official corporate action records.
- Enforces strict Point-in-Time universe filtering and constituent masking.
- Evaluates 20 auto-discovered delivery-research strategies with vectorized and event-driven backtesting.
- Enforces independent risk policies (position, gross exposure, sector exposure, daily loss, drawdown, and VaR).
- Executes forward-only paper sessions under `EOD_BATCH` and `TRUE_NEXT_OPEN` modes.
- Generates out-of-sample RCA correlation clusters and evaluates atomic 5-category promotion bundles.
- Serves an interactive Web Dashboard for inspecting runs, equity curves, fills, attribution, and data quality.

## Top-Level Entrypoints

- [`main.py`](../main.py): Orchestrates market data ingestion and live streaming client.
- [`research.py`](../research.py): CLI entrypoint for research, backtesting, RCA, walk-forward, and paper runs.
- [`scheduler.py`](../scheduler.py): Single-process advisory-locked task scheduler.
- [`run_pipeline.py`](../run_pipeline.py): Local pipeline orchestration wrapper.
- [`clean_db.py`](../clean_db.py): Research state reset utility.
- [`database_schema.sql`](../database_schema.sql): Authoritative DuckDB schema definition.
- [`README.md`](../README.md): Setup, usage, and project overview.
- [`requirements.txt`](../requirements.txt): Production Python dependencies.

## Configuration

- [`config/config.yaml`](../config/config.yaml): Active runtime config.
- [`config/config.example.yaml`](../config/config.example.yaml): Template config.
- [`config/symbols.yaml`](../config/symbols.yaml): Symbols, tokens, exchanges, and instrument types.

## Source Packages

### `smartapi/` (Broker Integration & Streaming)
- [`smartapi/auth.py`](../smartapi/auth.py): Handles login, token refresh, header creation.
- [`smartapi/historical.py`](../smartapi/historical.py): Fetches and normalizes historical candles.
- [`smartapi/instrument.py`](../smartapi/instrument.py): Downloads, caches, and queries instrument master data.
- [`smartapi/stream_decoder.py`](../smartapi/stream_decoder.py): High-performance binary packet decoder for SmartStream feeds.
- [`smartapi/stream_metrics.py`](../smartapi/stream_metrics.py): Feed latency, dispatch latency, and sequence gap tracking.
- [`smartapi/subscription_registry.py`](../smartapi/subscription_registry.py): Mode-aware subscription management and action payload building.
- [`smartapi/websocket_client.py`](../smartapi/websocket_client.py): Generation-isolated WebSocket streaming client with quarantine store.

### `storage/` (DuckDB Persistence & Migrations)
- [`storage/duckdb_manager.py`](../storage/duckdb_manager.py): Creates schema, upserts rows, executes atomic transactions, and logs audit events.
- [`storage/integrity.py`](../storage/integrity.py): Forensic database relational integrity and foreign-key validation.
- [`storage/migrations/runner.py`](../storage/migrations/runner.py): Checksum-validated schema migration runner (migrations 001 through 010).

### `data_platform/` (Data Contracts & Semantics)
- [`data_platform/contracts.py`](../data_platform/contracts.py): Normalized ticker modes, ticks, bars, quotes, and adjustments.
- [`data_platform/live_admission.py`](../data_platform/live_admission.py): Market data admission validator and tick filtering.
- [`data_platform/providers.py`](../data_platform/providers.py): Provider abstraction layer (Angel One, DuckDB Cache, OpenBB).
- [`data_platform/service.py`](../data_platform/service.py): Unified market data ingestion service.
- [`data_platform/source_semantics.py`](../data_platform/source_semantics.py): Corporate action detection, `PriceAdjustmentEngine`, and basis transformation.
- [`data_platform/universe.py`](../data_platform/universe.py): Point-in-Time universe filtering and snapshot membership.

### `trading_stack/` (Execution, Strategies & Paper Trading)
- [`trading_stack/domain.py`](../trading_stack/domain.py): Shared market, order, fill, `OpeningTickObservation`, and run models.
- [`trading_stack/calendars.py`](../trading_stack/calendars.py): NSE and global market session calendars with annualization logic.
- [`trading_stack/features.py`](../trading_stack/features.py): Causal feature factory.
- [`trading_stack/strategies.py`](../trading_stack/strategies.py): Strategy base contracts and auto-discovery registry.
- `trading_stack/strategy_library/`: 20 delivery-research strategies (9 single-asset, 11 cross-sectional).
- [`trading_stack/backtest.py`](../trading_stack/backtest.py): Vectorized and event-driven backtest engines.
- [`trading_stack/costs.py`](../trading_stack/costs.py): Side-aware Indian delivery statutory and broker cost schedules.
- [`trading_stack/datasets.py`](../trading_stack/datasets.py): `SynchronizedPanelBuilder` with PIT constituent masking and exact frame certification.
- [`trading_stack/live_aggregator.py`](../trading_stack/live_aggregator.py): Multi-window event-time watermark live bar aggregator with stream re-anchoring.
- [`trading_stack/paper.py`](../trading_stack/paper.py): Single-asset forward paper trading engine (`EOD_BATCH` and `TRUE_NEXT_OPEN`).
- [`trading_stack/portfolio.py`](../trading_stack/portfolio.py): `PortfolioEventBacktester` with liquidity caps, partial fills, and causal lagged ADV.
- [`trading_stack/portfolio_paper.py`](../trading_stack/portfolio_paper.py): Forward-only cross-sectional portfolio paper session engine.
- [`trading_stack/certification.py`](../trading_stack/certification.py): `RunCertificationService` evaluating exact 5-category evidence bundles.
- [`trading_stack/promotion.py`](../trading_stack/promotion.py): Deterministic research-to-paper promotion gates evaluating stitched OOS returns.
- [`trading_stack/rca.py`](../trading_stack/rca.py): Out-of-sample correlation clustering, overlap analysis, and loss attribution.

### `risk/` (Deterministic Risk Management)
- [`risk/engine.py`](../risk/engine.py): Independent `RiskEngine` evaluating order sizing, exposure, and limits.
- [`risk/models.py`](../risk/models.py): `RiskPolicy`, `RiskDecision`, and `RiskAction` domain contracts.
- [`risk/validators.py`](../risk/validators.py): `RequiredRiskStateValidator` and constraint validators.

### `experiments/` & `orchestration/`
- [`experiments/manager.py`](../experiments/manager.py): Reproducible experiment runner and provenance tracking.
- [`experiments/mass.py`](../experiments/mass.py): Resumable multi-strategy walk-forward research orchestrator.
- [`experiments/walk_forward.py`](../experiments/walk_forward.py): Chronological train/test window splitting.
- [`orchestration/engine.py`](../orchestration/engine.py): Task lifecycle management with non-overlapping worker retries.

### `tools/` & `tools/dashboard/` (Operational Tools & Web Dashboard)
- [`tools/import_nifty200.py`](../tools/import_nifty200.py): Official NIFTY 200 snapshot importer.
- [`tools/backfill_market_history.py`](../tools/backfill_market_history.py): Resumable multi-timeframe historical backfill.
- [`tools/database_recovery.py`](../tools/database_recovery.py): Backup, verification, and restore utility.
- [`tools/revalidate_historical_datasets.py`](../tools/revalidate_historical_datasets.py): Data quality revalidation runner.
- [`tools/dashboard/api/main.py`](../tools/dashboard/api/main.py): FastAPI backend providing read-only endpoints for runs, metrics, and data quality.
- `tools/dashboard/ui/`: Vite + React + TypeScript web application frontend.

### `validators/`
- [`validators/data_quality.py`](../validators/data_quality.py): In-memory data quality validation for missing candles, duplicates, and OHLC integrity.
- [`validators/duckdb_quality.py`](../validators/duckdb_quality.py): In-database data quality validator implementing the 6 required child checks.

## Documentation Index

- [`docs/architecture.md`](architecture.md): Architecture boundaries and target-state design.
- [`docs/production_readiness.md`](production_readiness.md): Production readiness status and verification evidence.
- [`docs/traceability_matrix.md`](traceability_matrix.md): Invariant and audit finding traceability.
- [`docs/operator_runbook.md`](operator_runbook.md): Operator runbook for maintenance and incidents.
- [`docs/backtesting.md`](backtesting.md): Backtesting models and execution realism.
- [`docs/risk_management.md`](risk_management.md): Risk management policies and limits.
- [`docs/data_sources.md`](data_sources.md): Data sources, adjustments, and providers.
- [`docs/strategies.md`](strategies.md): 20 strategy specifications.
- [`docs/security.md`](security.md): Security and credential safety.
