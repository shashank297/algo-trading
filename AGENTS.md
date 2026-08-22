# Repository Guidelines

## Project Structure & Module Organization

`main.py` is the Angel One ingestion entrypoint; `research.py` runs backtests, experiments, RCA, and paper sessions. Core trading code lives in `trading_stack/`, with strategies under `trading_stack/strategy_library/`. Provider-neutral data contracts are in `data_platform/`; broker integration is in `smartapi/`; persistence is managed by `storage/` and `database_schema.sql`. Risk, experiments, orchestration, validation, and shared helpers live in their matching top-level packages. Tests are in `tests/`. Operational scripts belong in `tools/`, configuration in `config/`, generated reports in `reports/`, and runtime logs in `logs/`.

### Top-level scripts vs. `tools/`

Three top-level scripts exist alongside `main.py`/`research.py`/`scheduler.py` and are easy to
confuse with `tools/`:

- `run_pipeline.py` — a thin orchestration wrapper that shells out to `main.py`/`research.py` in
  stages for a full local pipeline run; use it as a one-command "run everything" entrypoint.
- `clean_db.py` — destructively clears research-run tables (`strategy_runs`,
  `strategy_metrics`, orders/fills/attribution, equity curves) from `market_data.duckdb`; use
  only to reset local research state, never against a database you want to keep.
- `validate_cache.py` — a manual, ad-hoc check that `mass-research` job caching/skip-on-rerun
  behavior works as expected; not part of the automated test suite.

`tools/` holds everything else operational (backfills, imports, recovery, the dashboard). If you
add a new one-off script, prefer `tools/` unless it specifically orchestrates or resets the
top-level pipeline the way the three scripts above do.

## Build, Test, and Development Commands

Use the repository virtual environment on Windows:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m compileall -q main.py research.py trading_stack tests
.\venv\Scripts\python.exe main.py --universe-snapshot NIFTY200_2026_08_17
.\venv\Scripts\python.exe research.py --command universe-status --universe-snapshot NIFTY200_2026_08_17
```

Run a focused test while developing, for example `-m pytest tests/test_historical.py -q`. Do not run concurrent commands that write to `market_data.duckdb`; DuckDB permits only one writer process.

## Coding Style & Naming Conventions

Use Python 3.12+ syntax, four-space indentation, type hints, and short docstrings for public APIs. Follow existing naming: `snake_case` for modules/functions/variables, `PascalCase` for classes, and uppercase values for enums/constants. Keep strategy logic causal and provider-neutral. No formatter or linter is currently enforced, so match surrounding code and keep imports grouped. Prefer small, surgical changes over broad refactors.

## Testing Guidelines

Tests use `pytest` and files follow `tests/test_*.py`. Add deterministic tests for every behavioral change, especially next-bar execution, timezone/calendar handling, costs, risk limits, and persistence. Mock broker and LLM calls; tests must not require network access or real credentials. Run the full suite before submitting changes.

## Commit & Pull Request Guidelines

Git history is not readable in this workspace, so use concise imperative commits such as `Add resumable minute backfill`. Keep each commit focused. Pull requests should describe behavior, risks, schema/config changes, commands run, and test results. Link relevant issues and include sample CLI output for workflow changes; screenshots are needed only for visual artifacts.

## Security & Data Safety

Never commit `config/config.yaml`, API keys, TOTP secrets, broker tokens, DuckDB files, or logs. Use environment variables documented in `config/config.example.yaml`. Live order routing must remain disabled. Never fabricate pre-listing prices or silently mix adjusted and unadjusted datasets.
