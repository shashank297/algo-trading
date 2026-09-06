# FAB-16 Trading Research Foundation Readiness

Date: 2026-09-06
Status: blocked; paper promotion remains locked.

## Objective and disposition

FAB-16 was decomposed into exactly seven required child workstreams in the existing Paperclip project **Algo Trading — Research, Backtesting & Paper Trading**. No new project, permanent agent, strategy, paper session, broker order, live capability, or capital deployment was created.

Canonical control-plane routing:

- Project: `bc59843d-1e91-4232-af11-19d37b952301`
- Workspace: `c9287bc6-63ea-488b-bec2-c2ff4c9e53ae`
- Repository: `C:\Python projects\algo trading`
- Parent: FAB-16

## Evidence inspected

FACT: `reports/FAB-10_candidate_strategy_evidence_20260906.md` records a PIT failure: `index_constituents_pit` has zero rows, the available snapshot is survivorship-biased, fixed charges are omitted from the diagnostic cost model, robustness was not run, and independent QA approval is absent.

FACT: `reports/campaign1_data_readiness_recovery_20260902.md` and `reports/campaign1_data_readiness_20260903.md` explicitly reject current constituents as historical PIT evidence and identify missing authoritative historical membership, lineage, and certification artifacts.

FACT: The repository already contains causal PIT and fail-closed tests in `tests/test_asset_state.py` and `tests/test_campaign1_governance.py`, certification coverage tests in `tests/test_certification_coverage.py`, cost/backtest code in `trading_stack/costs.py`, robustness code in `experiments/robustness.py`, and experiment lineage enforcement in `experiments/trials.py` and `experiments/walk_forward.py`.

INFERENCE: The foundation has partial implementation coverage, but the evidence is not sufficient for continuous strategy generation or paper promotion until the seven gates produce current, linked, independently reviewed artifacts.

UNKNOWN: Availability and authority of an external historical constituent source; this remains an explicit dependency for PIT readiness and is not fabricated or substituted.

## Child workstreams

| Issue | Accountable owner | Reviewer | Dependencies |
|---|---|---|---|
| FAB-17 Point-in-Time Universe Readiness | Engineering & Automation Lead | Independent QA / Risk Lead | — |
| FAB-18 Market Data Lineage Certification | Engineering & Automation Lead | Independent QA / Risk Lead | FAB-17 |
| FAB-19 Transaction Cost Framework | Research & Intelligence Lead | Independent QA / Risk Lead | FAB-18 |
| FAB-20 Robustness Validation Framework | Independent QA / Risk Lead | Engineering/Research owner plus independent sign-off | FAB-17, FAB-18, FAB-19, FAB-21 |
| FAB-21 Canonical Strategy KPI Framework | Research & Intelligence Lead | Independent QA / Risk Lead | FAB-18, FAB-19 |
| FAB-22 Strategy Registry and Experiment Traceability | Knowledge & Operations Lead | Independent QA / Risk Lead | FAB-18, FAB-21, FAB-20, FAB-23 |
| FAB-23 Risk Configuration Reconciliation | Independent QA / Risk Lead | Independent review and Board for hard risk changes | FAB-18, FAB-21 |

## Acceptance and safety gates

Every child has a named owner, deliverable, acceptance criteria, evidence requirement, reviewer, and definition of done. Child completion must include deterministic focused tests and a reproducible evidence artifact. Missing or ambiguous evidence must fail closed. Paper promotion remains locked until PIT, lineage, costs, robustness, canonical KPI, risk configuration, and independent QA/Risk gates pass.

## Rollback and next phase

Rollback status: no repository mutation, database mutation, credential use, broker interaction, or runtime capability change was performed by this decomposition heartbeat. Control-plane rollback is limited to withdrawing/reassigning the seven child issues if the Board changes scope.

Next phase: accountable child owners execute within the existing project/workspace; independent QA/Risk reviews material outputs; the Board is escalated for any hard risk change, threshold exception, external credential/source decision, or paper-promotion decision.

## Continuation verification (2026-09-06)

Focused verification passed: `35 passed` across `tests/test_foundation_certification.py`,
`tests/test_kpi_contract.py`, `tests/test_transaction_cost_framework.py`,
`tests/test_universe_pit.py`, and `tests/test_run_pipeline.py`.

The parent remains blocked because the certification artifact still records blocked PIT,
lineage, risk-configuration, and independent-QA/Risk gates, plus a failed robustness gate.
The unblock owners and actions are recorded in `reports/FAB-25_foundation_remediation_20260906.md`;
no permissive threshold, current-constituent substitute, database repair, broker action, or
paper-promotion exception was taken.

## Decision log and retrospective seed

- Decision: use one existing project and canonical workspace; reason: routing invariant and reproducibility.
- Decision: create seven children only; reason: these are the minimum gates named by the Board request. Continuous-improvement design and failure-taxonomy aggregation remain Knowledge/Ops concerns, not new projects or workstreams here.
- Decision: preserve fail-closed behavior and explicit unknowns; reason: current PIT authority is unavailable in the inspected evidence.
- Lesson: dependency wiring can cause blocked child assignment drift in the control plane; assignments were re-verified and corrected for FAB-18 and FAB-22.
- Lesson for next phase: each child must attach focused tests and an evidence artifact before requesting review; a passing code path without authoritative data lineage is not sufficient.
