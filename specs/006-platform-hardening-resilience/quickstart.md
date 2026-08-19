# Quickstart & Verification: Platform Hardening & Ingestion Resilience

## Verification Steps

### 1. Test Suite Execution
```powershell
.\venv\Scripts\python.exe -m pytest tests/ -q
```
Expected: All tests pass (108+ passed).

### 2. Strategy Overview Aggregation Test
Query the API endpoint:
```powershell
curl http://127.0.0.1:8000/api/strategies
```
Expected: All strategies return non-zero/valid `total_stocks` without empty string groupings.

### 3. Instrument Master Cache Test
Run instrument download in Python:
```powershell
.\venv\Scripts\python.exe -c "from main import load_yaml; from smartapi.instrument import InstrumentMaster; im = InstrumentMaster(load_yaml('config/config.yaml')); im.download_instrument_master()"
```
Expected: Second run loads instantaneously with a log indicating cached data was loaded.
