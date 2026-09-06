# FAB-25 Foundation Remediation & Certification

## Disposition

`BLOCKED`: the machine-readable certification is [FAB-25_foundation_certification_20260906.json](FAB-25_foundation_certification_20260906.json). No strategy, paper session, broker order, credential, live endpoint, capital deployment, project, or agent was created.

## Blocker matrix

| Gate | Class | Status | Evidence / unblock action |
|---|---|---|---|
| PIT | External data dependency | BLOCKED | Authoritative historical NIFTY 200 membership is unavailable. Supply dated membership, known-at timestamps, source certification, coverage, and hash per the PIT requirement; do not use current constituents. |
| Lineage | Internal + data dependency | BLOCKED | Authoritative database/WAL and complete manifest are unavailable. Recover a readable immutable source and regenerate the complete manifest; incomplete manifests fail closed. |
| Transaction costs | Internal engineering | PASS | Explicit mandatory components and focused tests are evidenced; assumptions were not changed to improve results. |
| Robustness | Internal engineering | FAIL | Regime, missing-bar, and PIT-constituent sensitivity gates remain incomplete. |
| KPI | Internal engineering | PASS | Canonical contract and deterministic tests are evidenced. |
| Risk configuration | Governance / Board decision | BLOCKED | Conflicting material limits remain across config, docs, and defaults. Board must select the canonical policy; no permissive value was silently chosen. |
| Independent QA/Risk | Governance control | BLOCKED | Fresh independent review is still required and must return exactly PASS, PASS_WITH_CONDITIONS, FAIL, or BLOCKED. |

## Exact PIT Data Requirement Specification

Provide an authoritative historical NIFTY 200 membership dataset covering every requested research date, with canonical instrument identity, `effective_from`, `effective_until`, `known_from`/announcement timestamp, inclusion and exclusion reason, source URL or document identifier, retrieval timestamp, source certification, complete coverage interval, deterministic content hash, and a manifest binding the membership data to the market-data datasets. The source must support former constituents and delistings. Current constituent snapshots are explicitly unacceptable as historical PIT evidence.

## Review and next phase

Facts are distinguished from inference in the linked FAB-16/FAB-17/FAB-20/FAB-23 reports. Unknown and not-run states are not promoted to pass. Rollback status: no destructive action or runtime capability change; new evaluator, tests, artifact, and report are additive. Unblock owners are Data Engineering for PIT/lineage, Engineering/Research for robustness, the Board for material risk policy, and Independent QA/Risk for final review. After that review, stop and record the exact verdict and evidence.
