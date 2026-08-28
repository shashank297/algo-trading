# Phase 2.4 Quickstart

Configure `research.regime_transition` in `config/config.yaml`, using separate EOD/INTRADAY maximum
durations. Leave stress override disabled until explicit thresholds are approved.

```powershell
.\venv\Scripts\python.exe research.py --command market-regime --context EOD --as-of 2026-08-27 --universe-snapshot NIFTY200
.\venv\Scripts\python.exe research.py --command market-regime --context INTRADAY --as-of 2026-08-27 --decision-time 2026-08-27T10:00:00+05:30 --universe-snapshot NIFTY200
```

The JSON response contains both `raw_regime` and `operational_regime`, plus hysteresis and stress state details.
