# Pre-Strategy-Factory Hardened Baseline Audit Report

**Date**: 2026-09-06  
**Repository**: `shashank297/algo-trading`  
**Workspace**: `C:\Python projects\algo trading`  
**Authoritative Reference**: FAB-31 / FAB-32 Foundation Hardening Baseline  

---

## 1. Executive Summary & Governance Disposition

| Governance Control | Status | Details |
| :--- | :--- | :--- |
| **Strategy Factory** | **BLOCKED** | Blocked on authoritative external NIFTY 200 PIT constituent dataset |
| **PIT Status** | **BLOCKED_EXTERNAL_DATA** | Awaiting certified provider historical membership data (2012–2026) |
| **NSE Inquiry Status** | **AWAITING_PROVIDER_RESPONSE** | Formal non-binding inquiry sent to `indices@nse.co.in` (FAB-32) |
| **Paper Trading** | **BLOCKED** | Closed until authoritative PIT certification and pipeline approval |
| **Live Capital** | **DISABLED** | `CAN_DEPLOY_REAL_CAPITAL = False` strictly enforced; no execution adapter |
| **Hardening PR** | **#20 (MERGED)** | Merged into canonical `main` under normal branch protection |
| **Canonical `main` SHA** | `c7581c7dbd740115382dc69d8ab7e5f20c6dab4f` | Post-merge HEAD on canonical `main` |
| **PR #20 Merge Commit** | `c7581c7dbd740115382dc69d8ab7e5f20c6dab4f` | Normal non-admin merge satisfying all 6 required CI checks |

---

## 2. Hardened Content Verification

The hardened baseline implements and verifies the following 14 core controls:

1. **Canonical Board-Approved Risk Policy v1.1.0**:
   - `policy_id`: `canonical-risk-policy-v1`
   - `policy_version`: `1.1.0`
   - `policy_hash`: `9839425d1c770c2b25744b110122c7b44cd3d7e4ee0e94dbb942dfa07f9d2092`
   - Status: `BOARD_APPROVED` under FAB-31
2. **Policy Hash Verification**:
   - Strict SHA-256 hash verification in `risk/factory.py`.
   - Fails closed on any discrepancy or missing policy file.
3. **Minimum Liquidity Floor**:
   - ₹5 Crore average daily turnover (`min_liquidity_crore = 5.0`).
4. **Maximum Gross Long-Only Exposure**:
   - Hard capped at 100% (`max_gross_exposure_pct = 1.00`, Pydantic validator `le=1.00`).
   - Zero leverage, margin borrowing, or short exposure authorized.
5. **No Implicit Authoritative RiskEngine Fallback**:
   - `risk/factory.py` strictly raises `ValueError` if configuration or hash verification fails.
6. **Diagnostic Risk Overrides**:
   - All overrides marked `override_reason="DIAGNOSTIC_NOT_PROMOTABLE"`, preventing promotion into authoritative research or paper pipelines.
7. **External Human/Board Approval Evidence**:
   - Persisted in DuckDB `external_approval_evidence` table (`approval_id = "board-approval-fab31-risk-policy-20260906"`).
8. **FoundationCertificationRegistry**:
   - Authoritative registry in `trading_stack/certification.py` enforcing checksums and certification gates.
9. **Foundation Artifact SHA Verification**:
   - Deterministic SHA-256 verification of foundation files.
10. **Uniform Execution Gates**:
    - `EOD_BATCH` / `TRUE_NEXT_OPEN` paper execution gates strictly enforced.
11. **Authoritative PIT Stable-Identity Requirement**:
    - Requires stable security identifiers / ISINs rather than fluctuating historical symbols alone.
12. **Lineage and Time Horizon Preservation**:
    - `known_at`, `effective_from`, and `effective_until` tracked end-to-end.
13. **DatasetLineageManifest & Verifier**:
    - Complete dataset provenance hashing in `data_platform/lineage.py`.
14. **Live-Capital Capability Disabled**:
    - `CAN_DEPLOY_REAL_CAPITAL = False` certified across all modules; live routing prohibited.

---

## 3. Pull Request and Branch Protection Status

- **PR**: #20 (`https://github.com/shashank297/algo-trading/pull/20`)
- **Base**: `main`
- **Merge Status**: **MERGED** (`state: MERGED`, `mergeStateStatus: CLEAN`)
- **Merge Commit**: `c7581c7dbd740115382dc69d8ab7e5f20c6dab4f`
- **Branch Protection on `main`**:
  - `enforce_admins: true`
  - `strict: true`
  - Required checks: `test (ubuntu-latest, 3.13)`, `test (ubuntu-latest, 3.12)`, `test (windows-latest, 3.12)`, `quality`, `frontend`, `secrets`
- **GitHub Actions CI Status**: **ALL GREEN (6/6 passing)**
  - `test (ubuntu-latest, 3.13)`: SUCCESS (5m33s / 5m26s)
  - `test (ubuntu-latest, 3.12)`: SUCCESS (5m31s / 8m47s)
  - `test (windows-latest, 3.12)`: SUCCESS (20m24s / 29m34s)
  - `quality`: SUCCESS (7m47s / 7m34s)
  - `frontend`: SUCCESS (19s)
  - `secrets`: SUCCESS (9s / 10s)

---

## 4. Deterministic Verification Suite Results

### Full Repository Test Suite
```powershell
.\venv\Scripts\python.exe -m pytest -q
```
**Result**: **859 passed in 534.79s (100% PASS, 0 failures)**

### Post-Merge Smoke Verification on `main`
```powershell
.\venv\Scripts\python.exe -m pytest tests/test_foundation_hardening.py -q
```
**Result**: **13 passed in 12.70s (100% PASS)**

### Code Quality & Static Typing
- `ruff check .`: **All checks passed!**
- `compileall`: Clean across all packages
- `mypy`: **Success: no issues found in 107 source files**
- `pyright`: **0 errors, 0 warnings**
- `coverage`: Overall 85% (gate >=80%), Critical components 95% (gate >=95%), Experiments 95% (gate >=95%)
- `frontend`: `npm run lint` clean (0 errors), `npm run build` successful

---

## 5. Conclusion & Operational State

The foundation hardening codebase and all 14 governance controls have been successfully integrated into canonical `main` (`c7581c7dbd740115382dc69d8ab7e5f20c6dab4f`) via standard protected merge without administrative bypass.

Operating State:
- **PIT**: `BLOCKED_EXTERNAL_DATA`
- **NSE Inquiry**: `AWAITING_PROVIDER_RESPONSE`
- **Strategy Factory**: `BLOCKED`
- **Paper Trading**: `BLOCKED`
- **Live Capital**: `DISABLED`

Baseline is certified and immutable pending official response from NSE Indices Ltd.
