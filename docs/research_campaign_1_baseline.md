# Strategy Research Campaign 1 Baseline

This declaration freezes the research infrastructure and economic assumptions for
Campaign 1. It is documentation-only: no experiment is started by recording it.

## Identity

| Field | Frozen value |
| --- | --- |
| `CAMPAIGN_BASELINE_ID` | `campaign-1-2d653914799e` |
| `MAIN_SHA` | `8755cecf301ac099754fc490ec657610b4da4347` |
| Research configuration hash | `ec50bff064bed0d2b4ff59a97961467d2225a4e3511ac8155f8555b8f66a1357` |
| `RISK_POLICY_HASH` | `8330bb013ffd1d22acb2c60d715066a43b239cd35b382e772c4a7d47c7d72a3c` |
| `COST_POLICY_IDENTITY` | `52e6a43699be4daee483c7503742b033235b0e47d918782ce74cf811aae8e79f` |
| Feature version | `features-v1` |
| Economic semantics version | `current_mark_to_market_equity_v1/floor_whole_share_v1` |
| Asset class | `INDIA_EQUITY` |
| Canonical execution | `event-driven` |
| Starting capital | `INR 100000` |
| Paper starting capital | `INR 100000` |
| `research.live_trading` | `false` |

## Status

- **CODE / GOVERNANCE STATUS:** Campaign 1 PIT/governance hardening verified.
- **DATA STATUS:** Campaign 1 data readiness blocked.
- `EXTERNAL HISTORICAL CONSTITUENT DATA REQUIRED`.

## Frozen Assumptions

- Risk authority is the complete configured `research.risk` policy. Its material
  fields and policy hash must not be changed during Campaign 1.
- Historical execution uses date-effective Indian delivery schedules. Fixed-cost
  schedules are reserved for explicitly labelled stress tests.
- Sizing uses current marked-to-market equity: cash plus holdings marked only at
  causally available prices. Shares are rounded down to whole shares using the
  existing authoritative semantics.
- Vectorized execution is screening/preliminary only. Promotion, robustness,
  Phase 2.8 eligibility, Phase 2.10 evidence, frozen policies, and paper-promotion
  ranking require authoritative event-driven execution.
- `NIFTY200_CURRENT` is the configured universe identity and is marked
  survivorship-biased. It is not a claim of point-in-time historical validity;
  authoritative historical promotion requires an immutable PIT universe snapshot.
- Phase 2.10 FINAL-OOS remains `PHASE 2.10 IMPLEMENTATION READY` unless the
  contractual certified non-synthetic evidence procedure passes.

## Cost Regimes

`COST_POLICY_IDENTITY` binds the date-effective schedule sequence currently
implemented by `get_cost_schedule`:

- `2010-01-01`: `angel-nse-delivery-2010-01`, schedule hash `6f4c1b3f...`
- `2016-06-01`: `angel-nse-delivery-2016-06`, schedule hash `fa4e0d50...`
- `2024-10-01`: `angel-nse-delivery-2024-10`, schedule hash `0f34303f...`
- `2026-04-01`: `angel-nse-delivery-2026-04`, schedule hash `9e21abfd...`

## Strategy Library

The frozen registry contains 21 strategies. Versions are resolved from
`StrategyRegistry` at the pinned SHA; no strategy is added or modified during
the campaign without a new approved baseline.

The merged implementation's strategy-library identity is
`ef5e1492b81c4e76f4f1e9c6fae4d54de4597b8eabb1af223fc4eee8174742d8`.

All registered strategies are version `1.0.0` except:

- `trend_following`: `1.1.0`
- `mean_reversion`: `1.1.0`
- `opening_range_breakout`: `1.1.0`

## Re-baselining Rule

Any material change to risk policy, costs, execution mode, causal sizing,
rounding, feature definitions, universe/PIT policy, or strategy versions creates
a new campaign baseline. This declaration must not be silently amended while
Campaign 1 is running.
