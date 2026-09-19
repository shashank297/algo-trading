# Quickstart & Verification Guide

## 1. Environment Setup

Ensure dependencies are installed using the tracked requirements:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. Focused Regression Tests

Run focused test suites covering risk sizing, approval authenticity, PIT identity, migrations, clean_db, scheduler, and dashboard:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_risk_sizing_regression.py -vv
.\venv\Scripts\python.exe -m pytest tests/test_approval_regression.py -vv
.\venv\Scripts\python.exe -m pytest tests/test_pit_candle_join.py -vv
.\venv\Scripts\python.exe -m pytest tests/test_migration_atomicity.py -vv
.\venv\Scripts\python.exe -m pytest tests/test_clean_db.py -vv
.\venv\Scripts\python.exe -m pytest tests/test_scheduler.py -vv
.\venv\Scripts\python.exe -m pytest tests/test_dashboard_api.py -vv
.\venv\Scripts\python.exe -m pytest tests/test_ai_risk_regression.py -vv
.\venv\Scripts\python.exe -m pytest tests/test_campaign1_governance.py -vv
```

## 3. Static Analysis & Linting

```powershell
.\venv\Scripts\python.exe -m ruff check .
.\venv\Scripts\python.exe -m mypy ai_research/ tools/ data_platform/ storage/ risk/ trading_stack/ orchestration/
.\venv\Scripts\python.exe -m pyright
.\venv\Scripts\python.exe -m compileall -q main.py research.py run_pipeline.py scheduler.py tools ai_research data_platform risk storage trading_stack orchestration tests
git diff --check
```

## 4. Full Test Suite

```powershell
.\venv\Scripts\python.exe -m pytest -q
```
