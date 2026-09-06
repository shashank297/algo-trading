# FAB-20 Robustness Validation Framework — Independent QA/Risk Review

Date: 2026-09-06  
Reviewer: Independent QA / Risk Lead (`a36abc5d-4603-4c37-8e6b-186c0f905db7`)  
Scope: repository implementation and reproducible evidence only; paper-only execution remains in force.

## Verdict

**BLOCKED** — do not promote a candidate to paper validation or relax any threshold.

The implementation has useful, passing partial controls, but the FAB-20 acceptance contract is not complete and no deterministic PASS/CONDITIONAL/FAIL/BLOCKED verdict artifact is implemented by the framework.

## Evidence and acceptance results

| Acceptance control | Expected behavior | Observed evidence | Result |
|---|---|---|---|
| Walk-forward / OOS separation | Final OOS cannot affect selection | `tests/test_robustness.py::test_nested_wf_sealed_final_oos_leakage_prevention`; 34/34 focused tests pass | PASS (partial scope) |
| Purge and embargo | Boundary leakage is removed and invalid windows fail closed | Splitter tests and `test_purge_window_exhaustion_fail_closed` pass | PASS |
| Parameter/window perturbation | Stable neighborhood selection with explicit perturbation evidence | `ParameterRobustnessSelector` and plateau/sensitivity tests pass | PASS (parameter only; window sensitivity not separately gated) |
| Cost stress | OOS cost stress at 1.0x/1.5x/2.0x/3.0x, deterministic and monotonic | Cost stress tests pass; missing fill/timestamp evidence fails closed | PASS (cost component) |
| Missing-bar/data-quality stress | Explicit missing-bar and quality perturbation gate with verdict impact | No missing-bar/data-quality stress gate or corresponding deterministic acceptance test found | FAIL / blocker |
| Regime/constituent sensitivity | Explicit regime and PIT constituent sensitivity evidence | No regime/constituent sensitivity implementation or test found; PIT dependency is currently blocked in FAB-17/FAB-18 | FAIL / blocker |
| Multiple-testing / selection disclosure | Authoritative registry-backed trial multiplicity and selection disclosure | DSR resolver and registry linkage tests pass; failed/invalidated/deduplicated trials are covered | PASS (component) |
| Deterministic verdict | Framework emits PASS/CONDITIONAL/FAIL/BLOCKED deterministically | `RobustnessBundle.evidence_status` only uses `EvidenceStatus.VALID` or `INSUFFICIENT_EVIDENCE`; no required four-way verdict field/decision function/artifact found | FAIL / hard blocker |
| Threshold governance | No post-result relaxation without Board approval | No threshold relaxation was observed in this review; policy values are configurable and no Board approval binding is represented in the robustness bundle | CONDITIONAL; must be explicit before approval |
| Reproducibility / persistence | Immutable, hash-bound bundle can be rerun and audited | Migration 022, idempotency/conflict, lineage/hash tests pass | PASS (implementation evidence) |

## Test command and observed output

Command:

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_robustness.py -q
```

Observed: **34 passed in 46.52s**.

This is necessary evidence, not sufficient acceptance evidence: the passing suite does not cover the missing-bar/data-quality, regime/constituent, four-way verdict, or Board-governed threshold controls.

## Hard blockers and unblock actions

1. **Framework gate gap — implementation/research owner:** add explicit missing-bar/data-quality stress, regime sensitivity, and PIT constituent sensitivity controls; add deterministic tests that prove each gate changes the final decision and fails closed on absent authoritative evidence.
2. **Verdict gap — implementation/research owner:** add a persisted, deterministic `PASS | CONDITIONAL | FAIL | BLOCKED` verdict with named reasons, required evidence, policy/version/hash inputs, and no implicit mapping from `INSUFFICIENT_EVIDENCE` to approval.
3. **Dependency gap — FAB-17/FAB-18 owners:** provide authoritative historical PIT universe and certified market-data lineage. Current repository evidence records these as blocked/unavailable; current constituents must not substitute for historical membership.
4. **Governance gap — Engineering/Research owner plus Board when needed:** bind threshold policy identity to the verdict and record Board approval for any threshold change. No relaxation is approved by this review.

## Limitations and safety disposition

- No live credentials, broker orders, paper sessions, or live capability were used or enabled.
- This review did not certify any strategy, dataset, or promotion decision.
- Existing implementation evidence is valuable but cannot substitute for the missing acceptance gates or blocked PIT/lineage dependencies.
- Rollback status: no code changes made by QA; the reviewed implementation remains unchanged. Revert/hold promotion by keeping the candidate workflow locked until the blockers above are resolved and independently retested.

**Required next phase:** implementation owner attaches the completed protocol, deterministic verdict tests, missing-gate evidence, blocker log, and Board-approved policy revision (if any), then requests a fresh independent QA/Risk review.
