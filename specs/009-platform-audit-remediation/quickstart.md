# Quickstart: Platform Audit Remediation Verification

**Feature**: `009-platform-audit-remediation`

## Regression & Verification Commands

### 1. Run Focused Risk & Approval Regression Tests
```powershell
.\venv\Scripts\python.exe -m pytest tests/test_risk_sizing_regression.py -vv
.\venv\Scripts\python.exe -m pytest tests/test_approval_regression.py -vv
```

### 2. Run PIT Identity & Alias Validation
```powershell
.\venv\Scripts\python.exe -m pytest tests/test_pit_identity_regression.py -vv
```

### 3. Run Storage & Operational Tests
```powershell
.\venv\Scripts\python.exe -m pytest tests/test_migration_atomicity.py -vv
.\venv\Scripts\python.exe -m pytest tests/test_campaign1_governance.py -vv
```

### 4. Run Full Test Suite & Linting
```powershell
.\venv\Scripts\python.exe -m pytest -q
ruff check .
mypy risk trading_stack storage
```
