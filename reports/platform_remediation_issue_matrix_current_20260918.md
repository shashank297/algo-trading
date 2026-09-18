# Current platform and NIFTY-200 PIT issue matrix

This report is generated from the final rebuild whose manifest is
`artifacts/nifty200_pit_v1/evidence_manifest.json` with build ID
`452c2e431ac89ae42c9daab12224cbc438d64284913c36319e7e34428cbd107a`.
It supersedes neither older forensic reports nor mixed local changes; it records
the current measured state after the lineage and structural-importer repair.

## State

- Branch: `codex/platform-audit-remediation-clean`
- HEAD: `a8f383149187b8d0bbfb23253ba81c464ec8563f`
- Local `origin/main`: `a8f383149187b8d0bbfb23253ba81c464ec8563f`
- Automated validation: `BLOCKED`
- Independent QA: `NOT_ASSERTED`
- `approved_for_import`: `false`
- Campaign Stage A: not started
- Production database/WAL: not touched

## Issue matrix

| Issue ID | Reproduction/evidence | Affected area | Repair status | Regression/verification | Unresolved dependency |
|---|---|---|---|---|---|
| PLAT-001 | Current provider code previously fell through on authentication/integrity errors | `data_platform/providers.py` | FIXED | Platform regression suite previously passed | Full post-lineage suite still required |
| PLAT-002 | Risk inputs could use uncertified or unavailable market rows | `ai_research/workflow.py` | FIXED | Risk/platform regression tests previously passed | None identified in current code review |
| PLAT-003 | Destructive cleanup and backup/restore needed target and quiescence guards | `clean_db.py`, `operations/backup.py` | FIXED | Storage/platform tests previously passed | Disposable-database verification remains required |
| PLAT-004 | Approval verification required cryptographic issuer/stage/context binding | `trading_stack/approval.py`, `trading_stack/promotion.py` | FIXED | Approval regression tests and full suite pass | None identified in current verification |
| PLAT-005 | Current-master identity could be backdated into historical snapshots | PIT resolver and dataset join | FIXED IN SOFTWARE | PIT identity tests and structure-only importer pass | First-party historical identity evidence remains open |
| PLAT-006 | Raw evidence relationships were implicit | PIT reconciliation/manifest | FIXED IN SOFTWARE | 1,961 observations and 1,029 lineage links emitted | No authoritative event chain yet |
| PLAT-007 | Structural import checks were limited to manifest/hash and basic loading | PIT importer | FIXED IN SOFTWARE | `--validate-structure-only --dry-run`: 338 intervals validated, no DB write | Full import remains blocked by manifest validation state |
| PIT-001 | No authoritative membership list for 2012-01-02 | Initial anchor | OPEN | `anchor_status=NOT_ESTABLISHED`; 198-row candidate is diagnostic only; 5 checkpoint sets match and 102 mismatch | First-party anchor or complete backward chain |
| PIT-002 | 651 event assertions lack durable historical identity | Identity resolution | OPEN | 3,364 unresolved historical-master rows; durable/ISIN resolution 43.2906% | Period-valid official NSE/ISIN evidence |
| PIT-003 | 54 duplicate-add interval conflicts | Interval generation | OPEN | Conflict report retains all observation IDs | Official correction or event ordering evidence |
| PIT-004 | 6 same-day event collisions | Event causality | OPEN | Conflict report marks manual review | Official effective-date/publication ordering |
| PIT-005 | 68 months lack acquired checkpoints | Monthly coverage | OPEN | Monthly gap analysis classifies missing months | Free official checkpoint evidence or governed methodology decision |
| PIT-006 | 50 checkpoints contain 201 rows | Monthly parser/source semantics | RESOLVED IN SOFTWARE/POLICY | All 108 acquired checkpoints pass their expected count: 58×200 and 50×201, backed by two official Tata DVR notices; no non-expected checkpoint remains | None for the 201-row semantics; 68 months still lack any checkpoint |
| PIT-007 | Replay diagnostic produces 0–89 active members on all 3,609 sessions | Dependent replay validation | DEPENDENT | Count validation is explicitly not evaluable until the initial anchor is established; raw diagnostic counts remain in the manifest | Anchor, identities and events |
| PIT-008 | 724 raw observations remain unresolved/not canonicalized | Raw evidence closure | OPEN | `raw_unresolved_observations.csv` retained separately; 651 unresolved lineage blockers remain | Durable identity and/or causality evidence |
| DOC-001 | Older reports contain prior build IDs and metrics | Reports | OPEN | Current report created separately | Regenerate/label all historical reports |
| DOC-002 | `event_date_snapshots.parquet` is present but empty | Artifact completeness | OPEN | Schema exists; row count is 0 | Define evidence-backed event-date snapshot semantics |
| GOV-001 | Working tree is dirty and manifest records `UNCOMMITTED` code identity | Reproducibility | OPEN | Manifest records dirty execution identity | Commit reviewed code before certification |
| OPS-001 | Gitleaks unavailable in environment | Security verification | OPEN/ENVIRONMENT | `gitleaks` not installed | Install/use scanner in CI or approved environment |

## Current measured build

- Sources: 362 (`A1=361`, `A2=0`, `B1=1`); hash failures: 0
- Observations: 1,961; canonical events: 936 (`ADD=396`, `DROP=540`)
- Snapshots: 21,650 rows across 108 dates
- Valid expected-count checkpoints: 108 (`58×200`, `50×201`); missing/non-expected months: 68
- Current security-master rows: 2,568
- Historical identity rows: 6,886; unique instruments: 2,568
- Durable-ID/ISIN resolution: 43.2906%; unresolved identity: 3,364
- Intervals: 338
- NSE sessions: 3,609; diagnostic active range: 0..89; count validation evaluable: `false`
- Known-at unresolved: 0
- Conflicts: 989 (`HIGH=662`, `CRITICAL=327`)
- Raw observations retained: 1,961; unresolved raw rows: 724
- Lineage links: 1,029 (`UNRESOLVED=651`, `CORROBORATED=278`, `REDUNDANT=80`, `CONFLICTS_WITH=20`)
- Structure-only importer: passed, 338 intervals, no database write
- Approval-gated dry-run: refused because validation is `BLOCKED`

## Required next closure sequence

1. Obtain free first-party historical security-master/ISIN evidence for the unresolved labels.
2. Establish the 2012-01-02 anchor or a complete first-party backward chain.
3. Resolve duplicate and same-day event conflicts with official evidence.
4. Decide and document the checkpoint methodology without deleting 201-row source rows.
5. Define and implement event-date snapshot semantics if that artifact is required.
6. Rebuild, validate, rerun all tests/static checks, and compare the blocker ledger.
