# Phase 2.6 Quickstart & Verification Guide

## 1. Running Unit & Statistical Tests
```powershell
.\venv\Scripts\python.exe -m pytest tests/test_statistical_tests.py -vv
.\venv\Scripts\python.exe -m pytest tests/test_robustness.py -vv
```

## 2. CLI Robustness Command
```powershell
.\venv\Scripts\python.exe research.py --command robustness --strategy EMACrossover --timeframe 1d --universe-snapshot NIFTY200_2026_08_17
```

## 3. Full Verification Matrix
```powershell
.\venv\Scripts\python.exe -m compileall -q main.py research.py experiments storage tests
.\venv\Scripts\ruff.exe check .
.\venv\Scripts\mypy.exe ai_research data_platform experiments operations orchestration risk smartapi storage trading_stack validators tools main.py research.py scheduler.py
.\venv\Scripts\pyright.exe
.\venv\Scripts\coverage.exe run -m pytest -q
.\venv\Scripts\coverage.exe report --fail-under=80
.\venv\Scripts\coverage.exe report --include="risk/*.py,trading_stack/paper.py,trading_stack/portfolio.py,trading_stack/portfolio_paper.py,trading_stack/pipeline.py,trading_stack/datasets.py,trading_stack/certification.py,trading_stack/promotion.py,trading_stack/regime_transition.py,trading_stack/asset_state.py,smartapi/websocket_client.py,trading_stack/live_aggregator.py,storage/migrations/*.py,experiments/robustness.py,experiments/statistical_tests.py" --fail-under=95
.\venv\Scripts\pip-audit.exe -r requirements.txt
```
