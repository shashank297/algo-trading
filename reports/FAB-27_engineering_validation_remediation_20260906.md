# FAB-27 — Engineering validation remediation

Date: 2026-09-06
Scope: `nifty200_zero_cost_pit_package/liquid_universe_spec.py`

## Completed

- Added fail-closed validation for missing or malformed `as_of` and effective dates.
- Added safe finite-number checks for turnover and trading-day fields.
- Added HTTP(S) URL validation and exact lowercase SHA-256 validation.
- Made both `fail_closed_reasons` and `validate_rows` return rejection reasons instead of
  propagating malformed-row exceptions.
- Added adversarial tests covering both entry points.

## Fresh verification

```text
.\venv\Scripts\python.exe -m pytest -q nifty200_zero_cost_pit_package/test_liquid_universe_spec.py
7 passed in 0.06s

.\venv\Scripts\python.exe -m compileall -q nifty200_zero_cost_pit_package
exit code 0
```

## Disposition

This remediation closes the validator defects identified by Independent QA/Risk. FAB-27
remains **BLOCKED**: the complete independently reconciled first-party NSE/NSE Indices PIT
identity, listing/status, turnover, rebalance, portable manifest replay, and horizon coverage
evidence has not been delivered. Do not emit `CANDIDATE_ACCEPTABLE_FOR_BOARD_REVIEW`.

FAB-17 remains BLOCKED and `NIFTY200_HISTORICAL_PIT_DATA` remains unresolved.
