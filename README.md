# AlgoTrading — Research-First Systematic Trading Platform

## Portfolio research commands

```powershell
.\venv\Scripts\python.exe tools\import_nifty200.py --effective-date 2026-08-17 --snapshot-id NIFTY200_2026_08_17
.\venv\Scripts\python.exe main.py --universe-snapshot NIFTY200_2026_08_17 --benchmark NIFTY200
.\venv\Scripts\python.exe research.py --command universe-status --universe-snapshot NIFTY200_2026_08_17 --benchmark NIFTY200
.\venv\Scripts\python.exe research.py --command portfolio-experiment --strategy cross_sectional_momentum --universe-snapshot NIFTY200_2026_08_17 --benchmark NIFTY200 --mode event-driven
.\venv\Scripts\python.exe research.py --command paper --strategy trend_following --symbol RELIANCE-EQ --timeframe 1d
```

Complete resumable history backfill (2012 or the provider/listing boundary, whichever is later):

```powershell
.\venv\Scripts\python.exe tools\backfill_market_history.py --universe-snapshot NIFTY200_2026_08_17 --start-date 2012-01-01 --timeframes 1m,1d
```

Use `--symbols RELIANCE-EQ` and `--max-windows 2` for a bounded connectivity smoke test.

Snapshot portfolio experiments fail closed until `universe-status` reports `ready: true`.
Snapshot ingestion is daily-only, automatically resolves the exact NIFTY 200 Angel index token,
and performs a bounded overlapping repair of missing expected daily sessions. The first paper invocation intentionally creates no
orders; it establishes the watermark and pending target for a future eligible bar.

## Overview
This project is a local-first systematic trading research platform. It preserves the Angel One SmartAPI ingestion engine for Indian markets and adds reproducible research, backtesting, paper-trading controls, provider-neutral data contracts, and evidence-bound AI research.

The platform includes:
- SmartAPI authentication with TOTP and token refresh
- Instrument master download, caching, and lookup
- Historical data download with chunking and rate limiting
- DuckDB storage with idempotent upserts and audit logs
- Incremental updates with overlap-safe deduplication
- Data-quality validation
- 20 long-only delivery-research strategies with two execution scopes
- Resumable universe research with expanding walk-forward evidence
- Portfolio event replay with Indian delivery costs and liquidity limits
- RCA correlation clustering and deterministic paper-promotion gates
- Loguru logging and saved summary reports

Live trading is intentionally disabled. Historical results are research evidence only, not proof that a strategy will be profitable.

Python `3.12` and `3.13` are supported and exercised by CI.

## Project Structure
```text
AlgoTrading/
├── config/
│   ├── config.yaml
│   ├── config.example.yaml
│   ├── symbols.yaml
│   └── .gitignore
├── data/
│   └── instrument_master.json
├── logs/
├── smartapi/
│   ├── __init__.py
│   ├── auth.py
│   ├── historical.py
│   └── instrument.py
├── storage/
│   ├── __init__.py
│   └── duckdb_manager.py
├── tests/
│   ├── test_auth.py
│   ├── test_historical.py
│   ├── test_storage.py
│   └── test_validators.py
├── utils/
│   ├── __init__.py
│   ├── logger.py
│   ├── report.py
│   ├── retry.py
│   └── timezone.py
├── validators/
│   ├── __init__.py
│   └── data_quality.py
├── .gitignore
├── database_schema.sql
├── main.py
├── market_data.duckdb
├── README.md
└── requirements.txt
```

## Prerequisites
- Windows, Linux, or macOS laptop
- Python `3.12`
- Angel One trading account with SmartAPI access enabled
- SmartAPI API key
- Client code
- Trading PIN
- TOTP secret from the Angel One app

## Installation
```bash
pip install -r requirements.txt
```

## Configuration
### Environment Variables
Store SmartAPI credentials in environment variables instead of `config.yaml`:

- `SMARTAPI_API_KEY`
- `SMARTAPI_CLIENT_CODE`
- `SMARTAPI_PIN`
- `SMARTAPI_TOTP_SECRET`

The application reads these values at startup and overlays them on top of `config/config.yaml`.
Keep `SMARTAPI_BASE_URL` and `SMARTAPI_INSTRUMENT_MASTER_URL` in `config/config.yaml`.

Retry limits in `rate_limits` are applied to transient SmartAPI requests. Maintain
`data.market_holidays` with exchange holiday dates in `YYYY-MM-DD` format so data-quality
checks do not report expected market closures as missing candles.

### How to get SmartAPI API Key
1. Log in to the Angel One SmartAPI portal.
2. Create or open your app.
3. Copy the generated API key.

### How to get Client Code
Use the same Angel One client code that you use to sign in to your trading account.

### How to get TOTP Secret
Open the Angel One app, then go to `Profile -> TOTP`. Use the TOTP secret shown there with an authenticator-compatible flow.

### Create your local config
```bash
cp config/config.example.yaml config/config.yaml
```

PowerShell alternative:
```powershell
Copy-Item config/config.example.yaml config/config.yaml
```

Keep `config/config.yaml` for non-sensitive settings.
For SmartAPI secrets, export the environment variables above before running `python main.py`.

PowerShell example:
```powershell
$env:SMARTAPI_API_KEY="your-api-key"
$env:SMARTAPI_CLIENT_CODE="your-client-code"
$env:SMARTAPI_PIN="your-pin"
$env:SMARTAPI_TOTP_SECRET="your-totp-secret"
python main.py
```

## First Run
```bash
python main.py
```

## Incremental Updates
Run `python main.py` daily to keep data current.

Already-downloaded data is not duplicated. The downloader re-fetches from the latest stored candle date and relies on DuckDB primary-key deduplication to stay idempotent and recover cleanly from partial runs.

## GitHub Setup
```bash
git init
git remote add origin https://github.com/username/AlgoTrading.git
git add .
git commit -m "feat: Phase 1 initial setup"
git push -u origin main
```

`config.yaml` and `*.duckdb` are in `.gitignore` and will never be pushed to GitHub. The local `data/` and `logs/` folders are also ignored.

## Expected Output (first run)
Sample terminal output:

```text
2026-06-18 09:01:00 | INFO | __main__ | 🚀 AlgoTrading Phase 1 starting...
2026-06-18 09:01:01 | INFO | smartapi.auth | ✅ Login successful for client: ABC123
2026-06-18 09:01:03 | INFO | smartapi.instrument | 📦 Instrument master loaded: 97864 instruments
Downloading: 100%|████████████████████████████████| 10/10 [04:32<00:00, 27.24s/it]
╔══════════════════════════════════════════════════════════════╗
║        AlgoTrading Phase 1 — Download Summary              ║
╠══════════════════════════════════════════════════════════════╣
║ Run Date     : 2026-06-18 09:01:00 IST                     ║
║ Total Symbols: 10                                          ║
║ Timeframes   : 1m, 1d                                      ║
║ Duration     : 4m 32s                                      ║
╠══════════════════════════════════════════════════════════════╣
║ Symbol          TF    Candles   Inserted  Status           ║
║ NIFTY           1m    185,420      1,240  ✅ SUCCESS       ║
║ NIFTY           1d      1,580         12  ✅ SUCCESS       ║
║ SENSEX          1m          0          0  ❌ FAILED        ║
╠══════════════════════════════════════════════════════════════╣
║ Quality Issues:                                             ║
║  • NIFTY 1m: 2 issues                                      ║
║  • TCS-EQ 1m: 0 issues                                     ║
╚══════════════════════════════════════════════════════════════╝
```

## Verify Data
```bash
python -c "
import duckdb
c = duckdb.connect('market_data.duckdb')
print(c.execute('''
  SELECT symbol, timeframe, COUNT(*) as candles,
         MIN(timestamp), MAX(timestamp)
  FROM historical_candles
  GROUP BY symbol, timeframe
  ORDER BY symbol, timeframe
''').df())
"
```

## Troubleshooting
- `AG8001 / AG8002`: Token expired. The engine automatically refreshes and retries.
- `AB1009`: Symbol not found. Check the `token` and `exchange` in `config/symbols.yaml`.
- `429`: Rate limit reached. The engine automatically backs off and retries.
- Empty data: Check the symbol token, date range, trading session timing, and whether the market had valid candles for the requested span.

## Continuous Integration

Every push and pull request runs compilation and the full unittest suite on Python 3.12 and 3.13 via `.github/workflows/ci.yml`.

## Manual Smoke Guide
1. Fill `config/config.yaml` with your real SmartAPI credentials.
2. Run `python main.py`.
3. Confirm login succeeds and a log file appears under `logs/`.
4. Confirm `data/instrument_master.json` refreshes when stale or missing.
5. Confirm `market_data.duckdb` contains rows in `instrument_master`, `historical_candles`, `download_log`, and `quality_report`.
6. Run `python main.py` a second time and confirm most rows show `UP_TO_DATE` or low insert counts because duplicate candles are ignored.

## New Research Layer

The repository now includes a new `trading_stack/` package and a `research.py` entrypoint for:

- strategy templates
- vectorized and event-driven backtests
- paper-trading simulation
- feature persistence
- strategy run, order, fill, and reconciliation logging

Example:

```bash
python research.py --strategy trend_following --symbol NIFTY --timeframe 1d --mode vectorized
```

## Research Workflows

```bash
# Record a reproducible experiment
python research.py --command experiment --strategy trend_following --symbol NIFTY --timeframe 1d

# Run the event-driven paper workflow with conservative risk controls
python research.py --command paper --strategy trend_following --symbol NIFTY --timeframe 1d

# Inspect recorded experiments
python research.py --command inspect

# Run structured AI research; requires OPENAI_API_KEY
python research.py --command agent-research --strategy trend_following --symbol NIFTY --timeframe 1d

# Run resumable mixed-scope research
python research.py --command mass-research --strategies trend_following,cross_sectional_momentum --universe RELIANCE-EQ,TCS-EQ,HDFCBANK-EQ

# Run authoritative cross-sectional portfolio replay
python research.py --command portfolio-experiment --strategy low_volatility --universe RELIANCE-EQ,TCS-EQ,HDFCBANK-EQ,INFY-EQ,ICICIBANK-EQ

# Ingest all eligible members from the imported official NIFTY 200 snapshot
python main.py --universe-snapshot NIFTY200_2026_08_17
```

Running `python main.py` without the snapshot flag continues to use `config/symbols.yaml`. Snapshot ingestion fails explicitly if the snapshot is missing or contains no eligible members with Angel One tokens; it never silently falls back or mixes universes.

See `docs/production_readiness.md`, `docs/operator_runbook.md`, `docs/data_sources.md`, `docs/strategies.md`, `docs/backtesting.md`, `docs/rca.md`, `docs/risk_management.md`, and `docs/security.md` before running a paper workflow.
