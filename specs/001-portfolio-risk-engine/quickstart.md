# Quickstart

## Validation Scenarios
1. Setup tests: `.\venv\Scripts\python.exe -m pytest tests/test_risk_engine.py`
2. Run paper trading with a large risk override to observe rejection:
`python research.py --command paper --strategy trend_following --capital 100000 --risk-override-max-pos 5`
