# FAB-23 Risk Configuration Reconciliation

**Reviewer:** Independent QA / Risk Lead  
**Date:** 2026-09-06  
**Verdict:** **FAIL**

## Scope and acceptance basis

Reviewed the configured risk policy, policy model and factory, validators, research/paper construction paths, live-mode guard, and focused tests. Acceptance requires one authoritative set of units and limits; missing, ambiguous, or permissive values must fail closed; position, portfolio, order/drawdown, concentration, liquidity, and session controls must be evidenced; execution must remain paper-only.

## Reconciliation matrix

| Control | Documented contract | Example/active config | Runtime/default consumer | Evidence | Result |
|---|---|---|---|---|---|
| Position | 5% capital | 5% | `RiskPolicy` default 20% | `risk/models.py:28`, `config/config.yaml:211` | FAIL: unsafe default drift |
| Gross portfolio | 20% capital | 20% | default 100% | `risk/models.py:29`, `config/config.yaml:212` | FAIL: unsafe default drift |
| Daily loss | 1% in active config; docs state 1% | 1% | default 3% | `risk/models.py:30`, `config/config.yaml:213` | FAIL: unsafe default drift |
| Drawdown | 5% in active config; docs state 5% | 5% | default 15% | `risk/models.py:31`, `config/config.yaml:214` | FAIL: unsafe default drift |
| Sector concentration | 10% documented | 40% | default 40%; separate `risk_limits.yaml` says 20% | `docs/risk_management.md:7`, `config/config.yaml:215`, `config/risk_limits.yaml:5` | FAIL: three conflicting values |
| Open positions | 20 | 20 | default 20 | `config/config.yaml:216`, `risk/models.py:34` | PASS (subject to authoritative injection) |
| VaR | 2% | 2% | default 2% | `config/config.yaml:217`, `risk/models.py:35` | PASS (subject to state completeness) |
| Liquidity | Required control; no zero floor accepted | 0 Cr | default 0 Cr; validator skips when turnover is absent and zero floor allows all | `config/config.yaml:218`, `risk/models.py:36`, `risk/validators.py:145` | FAIL: permissive/ambiguous |
| Session/order gate | Paper-only; no live order route | `live_trading: false` | `validate_config` checks live flag only; no risk-section validation | `main.py:264-265`, `main.py:136` | CONDITIONAL: live flag guarded, risk config not |

Units are also not encoded in the policy field names: percentages are decimal fractions, while liquidity is crore turnover. This is documented by comments only and is vulnerable to a 5-vs-0.05 configuration error.

## Reproducible tests and observed behavior

Command:

```text
.\\venv\\Scripts\\python.exe -m pytest -q tests/test_risk.py tests/test_configuration.py tests/test_trading_stack.py tests/test_run_pipeline.py
52 passed in 5.34s
```

These tests cover positive paths for position, gross exposure, drawdown, daily loss, max positions, liquidity, reversal handling, malformed finite values, and live-mode rejection. They do **not** establish configuration reconciliation or reject permissive defaults.

Independent probes observed:

```text
RiskEngine().policy = position .20, gross 1.00, daily loss .03,
drawdown .15, sector .40, liquidity 0.0
40pct_sector_at_39k -> PASS, approved 1000.0
validate_config(config_without_research_risk) -> ACCEPTED
```

The last result used test credentials only and shows `main.validate_config` accepts a configuration with no `research.risk`; the later factory may fail only for selected research commands. The fallback in `ai_research/workflow.py:28` constructs the permissive default engine when no engine is injected.

## Blockers and required corrections

1. **Owner: implementation owner; Board approval required for any hard-limit change.** Select and record one canonical sector limit and liquidity floor, then make active config, example config, `risk_limits.yaml`, docs, and all consumers agree. Do not silently choose a more permissive value.
2. **Owner: implementation owner.** Remove permissive production-capable `RiskPolicy` defaults or make construction without an authoritative policy fail closed. `ResearchWorkflow` must not silently fall back to `RiskEngine()`.
3. **Owner: implementation owner.** Extend configuration validation to require the complete risk mapping, validate finite numeric ranges and explicit units, and reject zero/absent liquidity where the control is required.
4. **Owner: implementation owner.** Add deterministic tests for missing risk section, each missing field, zero/ambiguous liquidity, default-engine construction, sector-limit reconciliation, and paper/session order gates. Re-run the focused suite and attach output.
5. **Dependencies:** Market Data Lineage Certification and Canonical Strategy KPI Framework remain prerequisites; no paper session, order, live mode, or capital deployment is approved by this review.

## Rollback / handoff

No repository mutation to trading logic or limits was made by QA. Current safe state is to keep execution paper-only and block promotion/paper-readiness until the above corrections are independently re-tested. A future reviewer must compare the new matrix against the exact Board-approved policy revision and fresh test output.
