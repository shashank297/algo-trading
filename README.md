# AlgoTrading — Research-First Systematic Trading Platform

## Quickstart & Key Commands

### 1. Ingestion & Universe Setup
```powershell
# Import official NIFTY 200 snapshot
.\venv\Scripts\python.exe tools\import_nifty200.py --effective-date 2026-08-17 --snapshot-id NIFTY200_2026_08_17

# Ingest daily history for snapshot constituents
.\venv\Scripts\python.exe main.py --universe-snapshot NIFTY200_2026_08_17 --benchmark NIFTY200

# Verify Point-in-Time universe readiness
.\venv\Scripts\python.exe research.py --command universe-status --universe-snapshot NIFTY200_2026_08_17 --benchmark NIFTY200
```

### 2. Strategy Research & Backtesting
```powershell
# Cross-sectional portfolio event-driven backtest
.\venv\Scripts\python.exe research.py --command portfolio-experiment --strategy cross_sectional_momentum --universe-snapshot NIFTY200_2026_08_17 --benchmark NIFTY200 --mode event-driven

# Single-asset strategy research
.\venv\Scripts\python.exe research.py --strategy trend_following --symbol RELIANCE-EQ --timeframe 1d --mode vectorized

# Resumable multi-strategy walk-forward mass research
.\venv\Scripts\python.exe research.py --command mass-research --strategies trend_following,cross_sectional_momentum,low_volatility --universe-snapshot NIFTY200_2026_08_17
```

### 3. Forward Paper Trading Simulation
```powershell
# EOD_BATCH execution (signals executed at completed bar close)
.\venv\Scripts\python.exe research.py --command paper --strategy trend_following --symbol RELIANCE-EQ --timeframe 1d --execution-mode EOD_BATCH

# TRUE_NEXT_OPEN execution (signals execute at next session opening tick observation)
.\venv\Scripts\python.exe research.py --command paper --strategy trend_following --symbol RELIANCE-EQ --timeframe 1d --execution-mode TRUE_NEXT_OPEN
```

### 4. Interactive Web Dashboard
```powershell
# Start FastAPI backend (Read-Only connection to DuckDB)
.\venv\Scripts\python.exe -m uvicorn tools.dashboard.api.main:app --port 8000 --reload

# Start Vite/React frontend
cd tools\dashboard\ui
npm run dev
```

---

## Overview

This project is a local-first systematic trading research and simulation platform built for Indian equity markets (NSE). It combines the Angel One SmartAPI historical and streaming ingestion engine with reproducible backtesting, strict anti-lookahead causality invariants, fail-closed data quality gates, provider-neutral data contracts, and deterministic paper-trading controls.

### Key Capabilities
- **SmartAPI Ingestion**: TOTP authentication, token refresh, chunked history downloads, rate-limit backoff, and live binary WebSocket streaming.
- **Data Quality & Provenance**: Atomic 6-check DQ certification gate (`schema`, `ohlc_integrity`, `duplicates`, `session_alignment`, `missing_sessions`, `timestamp_integrity`), immutable dataset content hashing, and Point-in-Time universe filtering.
- **Corporate Actions Engine**: Automatic detection and adjustment of stock splits, consolidations, and dividends to generate canonical `SPLIT_ADJUSTED` research frames.
- **20 Delivery Research Strategies**: 9 single-asset and 11 cross-sectional ranking strategies auto-discovered from `trading_stack/strategy_library/`.
- **Causal Execution Engines**:
  - `VectorizedBacktester`: Fast screening with cost model integration.
  - `PortfolioEventBacktester`: Authoritative event replay with statutory Indian delivery costs (STT, stamp duty, exchange charges, GST, SEBI fee, DP charges), liquidity constraints (20-day lagged ADV participation caps), and partial fill tracking.
- **Risk Management**: Independent `RiskEngine` enforcing strict position size (5%), gross exposure (20%), sector exposure (10%), daily loss (1%), and VaR limits.
- **Root-Cause Analysis (RCA) & Promotion**: Out-of-sample correlation clustering, return overlap analysis, and deterministic research-to-paper promotion gates.
- **Web Dashboard**: Interactive UI visualizing strategy runs, equity curves, drawdown series, fills, trade attribution, and data quality metrics.

> **Safety Notice**: Live broker order routing is intentionally unavailable. All execution modes are deterministic research simulations and forward-only paper sessions.

---

## Project Structure

```text
algo-trading/
├── ai_research/              # Structured evidence-bound AI research agents
├── config/                   # Configuration files (YAML, symbols, market calendars)
├── data_platform/            # Provider-neutral data contracts, admission, universe management
├── docs/                     # Architectural, operational, risk, and security documentation
├── experiments/              # Reproducible experiment specs, managers, and mass walk-forward jobs
├── operations/               # Database backup, checksum verification, and recovery
├── orchestration/            # Local task lifecycle, retries, and approval workflows
├── risk/                     # Independent deterministic risk engine, policies, and validators
├── smartapi/                 # Angel One broker API, auth, historical download, binary WebSocket
├── specs/                    # Specification documentation and requirements checklists
├── storage/                  # DuckDB persistence, schema migrations (001-010), integrity checks
│   └── migrations/           # Versioned SQL migration scripts
├── tests/                    # Deterministic pytest suite (385+ tests, >=95% critical coverage)
├── tools/                    # Operational utilities, backfills, recovery scripts, and dashboard
│   └── dashboard/            # Interactive Web Dashboard
│       ├── api/              # FastAPI read-only backend
│       └── ui/               # Vite + React + TypeScript frontend
├── trading_stack/            # Core trading engine, calendars, features, execution, and paper
│   └── strategy_library/     # 20 auto-discovered delivery-research strategies
├── validators/               # Data quality and DuckDB integrity validators
├── database_schema.sql       # Authoritative DuckDB schema definition
├── main.py                   # Market data ingestion and live streaming entrypoint
├── research.py               # Research, backtesting, RCA, and paper trading CLI
└── scheduler.py              # Single-process advisory locked scheduling runner
```

---

## Installation & Setup

### Prerequisites
- Python `3.12` or `3.13`
- Node.js `20+` (for Dashboard UI)
- Angel One trading account with SmartAPI enabled

### Setup Virtual Environment
```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration
1. Copy the example configuration:
```powershell
Copy-Item config\config.example.yaml config\config.yaml
```
2. Set your SmartAPI credentials via environment variables:
```powershell
$env:SMARTAPI_API_KEY="your-api-key"
$env:SMARTAPI_CLIENT_CODE="your-client-code"
$env:SMARTAPI_PIN="your-pin"
$env:SMARTAPI_TOTP_SECRET="your-totp-secret"
```

---

## Quality Assurance & Verification

The codebase maintains rigorous quality gates with 100% clean passes:

```powershell
# 1. Run deterministic test suite (387 tests)
.\venv\Scripts\python.exe -m pytest -q

# 2. Run Ruff linter
.\venv\Scripts\python.exe -m ruff check .

# 3. Run Mypy static type checking (85 source files)
.\venv\Scripts\python.exe -m mypy ai_research data_platform experiments operations orchestration risk smartapi storage trading_stack validators tools main.py research.py scheduler.py

# 4. Run Pyright type checking
npx --yes pyright

# 5. Verify byte compilation
.\venv\Scripts\python.exe -m compileall -q main.py research.py scheduler.py ai_research data_platform experiments operations orchestration risk smartapi storage trading_stack validators tools tests

# 6. Verify test coverage gates (80% global, 95% critical path)
.\venv\Scripts\python.exe -m coverage run -m pytest -q
.\venv\Scripts\python.exe -m coverage report --fail-under=80
.\venv\Scripts\python.exe -m coverage report --include="risk/*.py,trading_stack/paper.py,trading_stack/portfolio.py,trading_stack/portfolio_paper.py,trading_stack/pipeline.py,trading_stack/datasets.py,trading_stack/certification.py,trading_stack/promotion.py,smartapi/websocket_client.py,trading_stack/live_aggregator.py,storage/migrations/*.py" --fail-under=95

# 7. Dependency vulnerability audit
.\venv\Scripts\python.exe -m pip_audit -r requirements.txt

# 8. Build Frontend Dashboard
cd tools\dashboard\ui ; npm run build ; cd ..\..\..
```

---

## Documentation Index

- [Architecture & Invariants](docs/architecture.md): Component boundaries, data flow, and target architecture.
- [Production Readiness](docs/production_readiness.md): Production readiness status, verified evidence, and operational prerequisites.
- [Traceability Matrix](docs/traceability_matrix.md): Mapping of all audit findings (P0-P2, E1-E15) to code and tests.
- [Operator Runbook](docs/operator_runbook.md): Procedures for data operations, backfills, backups, and recovery.
- [Operations Guide](tools/OPERATIONS.md): Quick reference for CLI commands, paper trading, and dashboard.
- [Backtesting Guide](docs/backtesting.md): Vectorized vs. event-driven execution, cost schedules, and walk-forward splits.
- [Data Sources & Adjustments](docs/data_sources.md): Providers, PIT universe isolation, and price adjustment policies.
- [Risk Management](docs/risk_management.md): Risk engine contract, position sizing, VaR, and exposure constraints.
- [Strategy Specifications](docs/strategies.md): Details of the 20 delivery-research strategies.
- [Security & Data Safety](docs/security.md): Credential isolation, agent sandboxing, and data privacy.
