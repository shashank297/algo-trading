# Strategy Research Campaign 1 Baseline v2

Date: 2026-09-10

SUPERSEDES: [research_campaign_1_baseline.md](research_campaign_1_baseline.md)

This version supersedes the foundation/economic identity declaration in the
previous baseline and its reference in the Campaign 1 specification. The previous
documents remain historical evidence. This is a documentation baseline, not an
experiment-family migration, foundation certificate, Board/QA approval, or launch
authorization. The specification's trial, causal, validation and OOS requirements
continue to apply.

**FOUNDATION HARDENED / BASELINE ALIGNED (DOCUMENTATION) / DATA READINESS BLOCKED**

## Verified foundation identities

`git fetch origin` followed by `git rev-parse origin/main` on 2026-09-10 returned
the SHA below; local HEAD matched it. PR #20 is merged. The family-validation fix
accompanying this document is an uncommitted change on that foundation, not code
already included in the pinned main SHA. Before any future certification, bind
the actual reviewed code revision containing the fix.

| Field | Value |
| --- | --- |
| Baseline document ID | `campaign-1-baseline-v2-20260910` |
| Campaign / experiment family ID | `campaign-1-2d653914799e` |
| Canonical `MAIN_SHA` | `c7581c7dbd740115382dc69d8ab7e5f20c6dab4f` |
| Canonical risk policy ID | `canonical-risk-policy-v1` |
| Canonical risk policy version / effective date | `1.1.0` / `2026-09-06` |
| Canonical `RISK_POLICY_HASH` | `9839425d1c770c2b25744b110122c7b44cd3d7e4ee0e94dbb942dfa07f9d2092` |
| Campaign strategy registry identity (20 eligible strategies) | `ef5e1492b81c4e76f4f1e9c6fae4d54de4597b8eabb1af223fc4eee8174742d8` |
| Complete eligible parameter-space identity | `60fe7db2f4480da394fc1cf6b9596fe9ab57222518e5d2d938bff83bc3f0c096` |
| Ordered 74 materialized root configurations identity | `23d1929822853a09cee0e41216f4e0f812ca5031c788b0ec363a74a5100af5ab` |
| Cost-policy identity | `52e6a43699be4daee483c7503742b033235b0e47d918782ce74cf811aae8e79f` |
| Feature version / timeframe | `features-v1` / `1d` |
| Economic semantics | `current_mark_to_market_equity_v1/floor_whole_share_v1` |
| Asset class / benchmark | `INDIA_EQUITY` / `NIFTY200` |
| Authoritative execution | `event-driven` |
| Starting / paper starting capital | INR 100000 / INR 100000 |
| Live trading / real-capital deployment | `false` / `CAN_DEPLOY_REAL_CAPITAL = False` |
| Authoritative PIT snapshot / certified data interval | Unresolved; must be certified before registration/execution |

The risk hash was recomputed and validated by
`risk.factory.load_canonical_risk_policy()` against `config/risk_policy.yaml`.
It also equals `economic_contract_hash(policy.to_risk_policy().model_dump())`.
The loader hashes the complete limits mapping; policy ID, version and effective
date are separately bound above. No manual replacement hash was invented.

Canonical limits: position 5%, gross long-only exposure 100%, daily loss 1%,
drawdown 5%, sector exposure 20%, 20 open positions, VaR 2%, and minimum average
daily turnover INR 5 crore. Diagnostic overrides do not establish promotable
evidence. Leverage, borrowing and short exposure are not authorized.

## Exact root definition

The registry has 21 strategies; only its 20 `paper_eligible` strategies enter the
74-root definition. `opening_range_breakout` version `1.1.0` is excluded. Eligible
strategies are version `1.0.0`, except `mean_reversion` and `trend_following`, both
`1.1.0`. Empty grids mean exactly one declared default configuration.

| Eligible strategy | Complete parameter grid | Roots |
| --- | --- | ---: |
| bollinger_pullback | window=[15,20,30]; standard_deviations=[1.5,2.0,2.5] | 9 |
| consistent_momentum | {} | 1 |
| cross_sectional_momentum | long_lookback=[126,252]; skip_recent=[10,21] | 4 |
| cross_sectional_short_term_reversal | {} | 1 |
| donchian_breakout | entry_window=[20,40,55]; atr_buffer=[0.0,0.25,0.5] | 9 |
| donchian_trend | entry_window=[40,55,80]; exit_window=[10,20,40] | 9 |
| fifty_two_week_high | {} | 1 |
| low_beta | {} | 1 |
| low_volatility | {} | 1 |
| mean_reversion | {} | 1 |
| momentum_reversal_volatility | {} | 1 |
| ohlcv_multi_factor | {} | 1 |
| residual_momentum | {} | 1 |
| rsi_pullback | entry_rsi=[5.0,10.0,15.0]; exit_rsi=[60.0,70.0,80.0] | 9 |
| sector_relative_momentum | {} | 1 |
| time_series_momentum | long_lookback=[126,252]; short_lookback=[63,126] | 4 |
| trend_following | {} | 1 |
| volatility_contraction_breakout | window=[15,20,30]; contraction_quantile=[0.15,0.25,0.35] | 9 |
| volume_confirmed_breakout | window=[20,40,55]; volume_multiplier=[1.25,1.5,2.0] | 9 |
| walk_forward_logistic | {} | 1 |
| **Total** | **6 x 9 + 2 x 4 + 12 x 1** | **74** |

`maximum_trials=74` counts root hypotheses (`parent_trial_id IS NULL`). Symbols,
folds and governed descendants retain root lineage; they do not expand the
hypothesis budget. Failed and losing attempts remain evidence, and relabeling a
root does not authorize a retry or new hypothesis.

The expected `ExperimentFamilySpec` is rebuilt on every ensure call and passed
to `DuckDBManager.register_experiment_family()`. Its canonical `definition_hash`
binds ID, hypothesis, names, versions, complete parameter space, universe,
timeframe, features, cost model, budget, selection metric, walk-forward design,
regime/asset-cluster conditions and source revision. Only `created_at` and
`operator_notes` are excluded by the existing model. A mismatch fails closed;
this declaration cannot replace or overwrite an incompatible persisted family.

The current family hypothesis is `Campaign 1 authoritative event-driven
Indian-equity screening`; selection metric is
`net_return_drawdown_turnover_stability`; walk-forward metadata is
`{"mode":"nested_expanding","purge":"configured","embargo":"configured"}`;
regime and asset-cluster conditions are empty. The existing source-revision
label remains `campaign-1-baseline`; it is not the Git SHA above. The final family
hash cannot be declared until the certified universe and exact supplied
`cost_model_version` are bound. The cost-policy identity in this document binds
the full date-effective sequence, not merely one current schedule version.

## Causality, lineage and certification requirements

- Use immutable certified historical PIT membership with stable security IDs /
  ISINs, additions, removals, former constituents and delistings. Enforce
  `known_at`, `effective_from` and `effective_until` at each decision. Current
  NIFTY 200 constituents must never substitute for historical membership.
- Require source certification, completeness evidence, certified market-data
  intersection, calendar/timezone checks, causal features and consistent
  adjustment policy. Never fabricate pre-listing prices or mix adjusted and
  unadjusted data silently. Bind dataset content hashes, PIT evidence hash,
  `DatasetLineageManifest` and exact research-frame certifications.
- Event-driven execution is authoritative, with next-observation causal pricing,
  marked-to-market equity sizing and floor-to-whole-share rounding. Vectorized
  results are preliminary only. Use date-effective Indian delivery schedules
  (2010-01-01, 2016-06-01, 2024-10-01, 2026-04-01); fixed costs are stress-only.
- Preserve nested expanding walk-forward, configured purge/embargo, robustness
  and registry-backed statistics, and sealed FINAL OOS. No results may be used
  to change acceptance thresholds, grids or the 74-root budget retroactively.
- Require checksum-verified active `FoundationCertificationRegistry` evidence
  bound to code, PIT, lineage, cost and risk identities. All required gates
  (PIT, LINEAGE, TRANSACTION_COSTS, ROBUSTNESS, KPI, RISK_CONFIGURATION,
  INDEPENDENT_QA_RISK) must satisfy existing policy; missing evidence is blocked.
- Require externally minted Human/Board and independent QA/Risk approvals for
  applicable stages, with valid scope, expiry, subject, certification, risk-policy
  and code bindings. The YAML governance declaration is not proof that persisted
  approval evidence is present or valid. No approval is minted by this document.

## Historical lineage and unresolved runtime alignment

| Previous identity | Superseding identity |
| --- | --- |
| Main `8755cecf301ac099754fc490ec657610b4da4347` | Main `c7581c7dbd740115382dc69d8ab7e5f20c6dab4f` |
| Risk `8330bb013ffd1d22acb2c60d715066a43b239cd35b382e772c4a7d47c7d72a3c` | Canonical v1.1.0 risk `9839425d1c770c2b25744b110122c7b44cd3d7e4ee0e94dbb942dfa07f9d2092` |

`run_pipeline.py` still pins the historical research configuration hash
`ec50bff064bed0d2b4ff59a97961467d2225a4e3511ac8155f8555b8f66a1357` and historical
risk hash above. These guards were not silently changed as part of a document
re-baseline. A complete reviewed runtime configuration and its new identity must
be reconciled with canonical v1.1.0 before any launch; the old hash must not be
presented as the current canonical configuration. Cost and strategy identities
remain unchanged. The private operational configuration was not read or altered.

Historical PIT data readiness remains **BLOCKED_EXTERNAL_DATA** until certified
evidence independently satisfies every gate. Existing reports describe missing
historical membership and database/WAL recovery concerns; the operational
database and WAL were not opened or recovered in this verification, so those
findings are not marked resolved. Stage A and all subsequent research/paper
stages remain blocked. Live capital remains disabled regardless of certification.

See [post-merge verification](../reports/campaign1_post_merge_verification_20260910.md)
for observed checks and their scope. Further material changes require an explicit
superseding baseline and applicable external review; no historical evidence may
be rewritten to make a mismatched family compatible.

## Identity reproduction (metadata only)

At the pinned foundation, without opening a database or starting a run:

```python
from experiments.trials import canonical_hash
from research import materialize_campaign_1_configurations
from risk.factory import load_canonical_risk_policy
from run_pipeline import _campaign_strategy_names
from trading_stack.costs import DEFAULT_COST_SCHEDULES
from trading_stack.economic import campaign_cost_policy_identity, economic_contract_hash
from trading_stack.strategies import StrategyRegistry

policy = load_canonical_risk_policy()
names = _campaign_strategy_names()
registry = [{"name": n, "version": StrategyRegistry.metadata(n).version} for n in names]
grids = {n: dict(StrategyRegistry.metadata(n).parameter_grid) for n in sorted(names)}
print(policy.policy_id, policy.policy_version, policy.policy_hash)
print(economic_contract_hash(registry))
print(canonical_hash(grids))
print(canonical_hash(materialize_campaign_1_configurations()))
print(campaign_cost_policy_identity(DEFAULT_COST_SCHEDULES))
```
