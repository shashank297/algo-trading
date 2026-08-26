# Quickstart & Verification Guide: Final Audit Remediation

## Verification Commands

To verify all audit gates and critical platform requirements:

```powershell
# 1. Full automated test suite
.\venv\Scripts\python.exe -m pytest -q

# 2. Linting
.\venv\Scripts\python.exe -m ruff check .

# 3. Static Type Analysis
.\venv\Scripts\python.exe -m mypy ai_research data_platform experiments operations orchestration risk smartapi storage trading_stack validators tools main.py research.py scheduler.py
.\venv\Scripts\python.exe -m pyright

# 4. Bytecode Compilation
.\venv\Scripts\python.exe -m compileall -q main.py research.py scheduler.py ai_research data_platform experiments operations orchestration risk smartapi storage trading_stack validators tools tests

# 5. Global & Critical Code Coverage
.\venv\Scripts\python.exe -m coverage erase
.\venv\Scripts\python.exe -m coverage run -m pytest -q
.\venv\Scripts\python.exe -m coverage report --fail-under=80
.\venv\Scripts\python.exe -m coverage report --include="risk/*.py,trading_stack/paper.py,trading_stack/portfolio.py,trading_stack/portfolio_paper.py,trading_stack/pipeline.py,trading_stack/datasets.py,trading_stack/certification.py,trading_stack/promotion.py,smartapi/websocket_client.py,trading_stack/live_aggregator.py,storage/migrations/*.py" --fail-under=95
```
