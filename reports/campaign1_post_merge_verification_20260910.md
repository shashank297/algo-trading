# Campaign 1 post-merge governance verification

Date: 2026-09-10 (Asia/Kolkata)

SUPERSEDES (current-status reporting only):
[strategy_factory_hardened_baseline_20260906.md](strategy_factory_hardened_baseline_20260906.md)

The historical report is preserved, including its pre-existing uncommitted
updates. This report records fresh verification; it does not retrospectively
certify earlier claims or modify historical evidence.

**FOUNDATION HARDENED / BASELINE ALIGNED (DOCUMENTATION) / DATA READINESS BLOCKED**

## Canonical merge and CI evidence

`git fetch origin` completed successfully. Both `git rev-parse origin/main` and
`git rev-parse HEAD` returned `c7581c7dbd740115382dc69d8ab7e5f20c6dab4f`.

GitHub CLI verification (`gh pr view 19/20 --json state,mergedAt,mergeCommit,url`)
returned:

| PR | State | Merged at (UTC) | Merge commit |
| --- | --- | --- | --- |
| [#19](https://github.com/shashank297/algo-trading/pull/19) | MERGED | 2026-09-06T03:19:57Z | `d23b9601ae77bef650def73391895c0f5f2dca2e` |
| [#20](https://github.com/shashank297/algo-trading/pull/20) | MERGED | 2026-09-06T16:42:27Z | `c7581c7dbd740115382dc69d8ab7e5f20c6dab4f` |

`gh run list --branch main --commit <canonical SHA>` returned completed successful
CI runs `34095587508` and `34046308444`. Inspection of
[run 34095587508](https://github.com/shashank297/algo-trading/actions/runs/34095587508)
with `gh run view 34095587508 --json jobs` verified all six jobs successful:

- quality
- frontend
- secrets
- test (windows-latest, 3.12)
- test (ubuntu-latest, 3.12)
- test (ubuntu-latest, 3.13)

These are canonical-main results. The current local family-validation patch has
not been committed, pushed or run through hosted CI. Branch-protection bypass
history and the historical report's test/coverage counts were not independently
re-audited; no fresh claim about them is made here.

## Family hardening and regression evidence

Root cause: `_ensure_campaign_1_family()` returned after checking only trial
budget and universe whenever the family existed, bypassing storage's complete
immutable definition check.

The helper now always constructs the full expected `ExperimentFamilySpec` and
calls `DuckDBManager.register_experiment_family(expected_family)`. The existing
storage/model hashing and immutability rules are unchanged. No family is deleted,
recreated or overwritten to resolve a mismatch.

Fifteen new parameterized cases cover identical-family idempotency and 14
immutable-field mutations: cost model, strategy versions, parameter space,
universe, budget, hypothesis, strategy names, timeframe, features, selection
metric, walk-forward design, source revision, regime conditions and asset-cluster
conditions. The cost/metadata attacks retain Campaign ID, 74 trials and correct
universe. Cases use isolated temporary databases, assert the existing stored
family remains unchanged, and assert no research trials are created.

Before the fix, the new subset returned **14 failed, 1 passed**: 12 mismatches
were accepted; universe and budget raised the older partial-check errors rather
than the canonical storage error. After the fix, all cases pass.

## Local verification

Interpreter: repository `venv/Scripts/python.exe`, Python 3.13.11; pytest 9.1.1.
Commands were run from the repository root. Automated test fixtures exercise
synthetic/mocked behavior, not operational Campaign or broker workflows.

| Command (prefixed with `.\venv\Scripts\python.exe`) | Observed result |
| --- | --- |
| `-m pytest tests/test_campaign1_governance.py -vv` | 29 passed in 31.15s |
| `-m pytest tests/test_research_trials.py tests/test_foundation_hardening.py tests/test_run_pipeline.py -q` | 51 passed in 49.12s |
| `-m ruff check .` | All checks passed; exit 0 |
| `-m mypy ai_research/` | Success: no issues found in 4 source files; exit 0 |
| `-m pytest -q` | 874 passed, 3 warnings in 889.34s; exit 0 |

The three warnings are `CorporateActionBasisWarning` from
`test_panel_builder_uncertified_and_corporate_actions`, reporting already
split-adjusted synthetic provider history. They did not fail the suite.

`git diff --check` also passed. No hosted-CI test count is inferred from the old
audit report; the local full-suite count is reported separately above.

## Baseline alignment

The new [Campaign baseline v2](../docs/research_campaign_1_baseline_v2.md) preserves
the old declaration and explicitly supersedes its foundation identities:

- Main: `8755cecf301ac099754fc490ec657610b4da4347` to
  `c7581c7dbd740115382dc69d8ab7e5f20c6dab4f`.
- Canonical risk: `8330bb013ffd1d22acb2c60d715066a43b239cd35b382e772c4a7d47c7d72a3c`
  to `9839425d1c770c2b25744b110122c7b44cd3d7e4ee0e94dbb942dfa07f9d2092`, policy
  `canonical-risk-policy-v1` version `1.1.0`.

`load_canonical_risk_policy()` recomputed/validated the policy hash. Source files
used to calculate risk, strategy, grid and cost identities matched `origin/main`.
Registry and cost identities are unchanged; the v2 baseline includes complete
grids, root counts and reproducible canonical hashes.

The runtime orchestrator still pins its older frozen risk and full research
configuration hashes. Documentation alignment does not migrate that contract.
A reviewed configuration/identity reconciliation and applicable approvals remain
required before launch. The full family hash remains dependent on an actual
certified PIT snapshot and supplied cost-model version; neither was fabricated.

## Foundation and external-data disposition

PR #20's code contains canonical risk validation, foundation artifact checksum
validation and `FoundationCertificationRegistry` (in
`trading_stack/foundation_certification.py`), external approval checks, stable PIT
identity requirements and dataset-lineage controls. The focused foundation tests
passed in the related suite. Engineering hardening does not establish an active
PASS certification for Campaign data or authorize research/paper execution.

Reviewed evidence includes:

- [2026-09-03 data readiness](campaign1_data_readiness_20260903.md): historical
  constituent data and authoritative dataset certification absent; database/WAL
  recovery unresolved at that audit.
- [FAB-25 foundation artifact](FAB-25_foundation_certification_20260906.json):
  stored verdict BLOCKED, including PIT/lineage/independent-QA blockers. This
  historical artifact was read, not replaced or treated as a current certificate.
- [FAB-30 provider report](FAB-30_nifty200_historical_pit_provider_confirmation_20260906.md):
  no certified provider/sample for the required horizon at that report date.
- [FAB-32 inquiry record](FAB-32_nifty200_pit_provider_inquiry_20260906.md): records
  an inquiry and awaiting provider response. Delivery and current mailbox status
  were not independently verified in this task; no external message was sent.

No certified historical PIT evidence satisfying every gate was established by
this verification. The operational database and WAL were not opened, modified,
recovered, deleted or checkpointed, and persisted approval/certification state was
not revalidated. Historical unresolved findings are carried forward, not asserted
to be newly observed database facts.

Remaining blockers: authoritative historical PIT membership/source certification,
complete market-data intersection and lineage, resolution of previously reported
database integrity concerns through a separately authorized process, reviewed
runtime baseline alignment, active foundation certification and applicable
external Human/Board plus independent QA/Risk approval. Robustness and other
acceptance evidence must satisfy all existing gates before promotion.

Campaign Stage A remains **BLOCKED**. No Campaign stage, 74-trial execution,
mass-research, strategy-selection experiment, operational backtest, paper session,
broker request or live order was started. `CAN_DEPLOY_REAL_CAPITAL = False` and
live-trading controls remain unchanged.
