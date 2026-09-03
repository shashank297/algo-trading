# Strategy Research Campaign 1 Specification

Status: ready for review. This specification does not start experiments, change
strategy code, or change the frozen Campaign 1 economic baseline.

## Campaign Identity

- `CAMPAIGN_ID`: `campaign-1-2d653914799e`
- Baseline: `docs/research_campaign_1_baseline.md` at merged `main` SHA
  `8755cecf301ac099754fc490ec657610b4da4347`
- Asset class: `INDIA_EQUITY`
- Starting and paper capital: `INR 100000`
- Canonical execution: authoritative event-driven
- Historical costs: date-effective Indian delivery schedules
- Fixed-cost schedules: stress testing only
- Risk: frozen configured `research.risk`
- Live trading: `false`

## Governance And Data Status

- **CODE / GOVERNANCE STATUS:** Campaign 1 PIT/governance hardening verified.
- **DATA STATUS:** Campaign 1 data readiness blocked.
- `EXTERNAL HISTORICAL CONSTITUENT DATA REQUIRED`.

## Universe Policy

Use an immutable, certified point-in-time universe snapshot with membership and
knowledge dates. The configured `NIFTY200_CURRENT` universe is marked
survivorship-biased and is screening-only; it must not supply promotion or FINAL
OOS evidence. Every authoritative dataset must pass the existing data-quality,
calendar, adjustment, and PIT certification gates.

## Data Period Available

The campaign period is the intersection of certified data available in DuckDB,
the selected PIT universe membership intervals, and the causal feature history
required by each strategy. The current configuration records universe data as
verified through `2026-08-17`; exact campaign start/end dates must be taken from
the selected certified dataset at family registration. No family may be
registered with an unresolved or survivorship-biased period.

## Strategy Inventory

This is the complete registry inventory at the frozen baseline. Parameter grids
are the declared `StrategyMetadata.parameter_grid` values; an empty grid means
one explicitly approved default configuration, not permission to search hidden
parameters.

| Strategy | Version | Family | Scope | Lookback | Parameter grid | Rebalance | Features | Constraints / execution requirements |
| --- | --- | --- | --- | ---: | --- | --- | --- | --- |
| `bollinger_pullback` | 1.0.0 | MEAN_REVERSION | SINGLE_ASSET | 200 | `window={15,20,30}; standard_deviations={1.5,2.0,2.5}` | DAILY | `close` | Long-only delivery; causal daily bars and event-driven next observation |
| `consistent_momentum` | 1.0.0 | MOMENTUM | CROSS_SECTIONAL | 253 | default only | MONTHLY | `close` | Long-only ranking; certified PIT universe and synchronized panel |
| `cross_sectional_momentum` | 1.0.0 | MOMENTUM | CROSS_SECTIONAL | 253 | `long_lookback={126,252}; skip_recent={10,21}` | MONTHLY | `close` | Long-only ranking; PIT universe and monthly event-driven rebalance |
| `cross_sectional_short_term_reversal` | 1.0.0 | MEAN_REVERSION | CROSS_SECTIONAL | 200 | default only | MONTHLY | `close` | Long-only ranking; PIT universe and synchronized panel |
| `donchian_breakout` | 1.0.0 | BREAKOUT | SINGLE_ASSET | 21 | `entry_window={20,40,55}; atr_buffer={0.0,0.25,0.5}` | DAILY | `high, low, atr` | Long-only delivery; causal channel and event-driven execution |
| `donchian_trend` | 1.0.0 | TREND | SINGLE_ASSET | 56 | `entry_window={40,55,80}; exit_window={10,20,40}` | DAILY | `high, low` | Long-only delivery; causal channel and event-driven execution |
| `fifty_two_week_high` | 1.0.0 | MOMENTUM | CROSS_SECTIONAL | 252 | default only | MONTHLY | `close, high` | Long-only ranking; PIT universe and synchronized panel |
| `low_beta` | 1.0.0 | FACTOR | CROSS_SECTIONAL | 252 | default only | MONTHLY | `close, benchmark_close` | Long-only ranking; certified benchmark and PIT universe |
| `low_volatility` | 1.0.0 | FACTOR | CROSS_SECTIONAL | 200 | default only | MONTHLY | `close` | Long-only ranking; PIT universe and synchronized panel |
| `mean_reversion` | 1.1.0 | MEAN_REVERSION | SINGLE_ASSET | 20 | default only | DAILY | `price_zscore` | Long-only delivery; causal rolling feature and event-driven execution |
| `momentum_reversal_volatility` | 1.0.0 | COMPOSITE | CROSS_SECTIONAL | 253 | default only | MONTHLY | `close` | Long-only ranking; PIT universe and synchronized panel |
| `ohlcv_multi_factor` | 1.0.0 | COMPOSITE | CROSS_SECTIONAL | 253 | default only | MONTHLY | `close, volume` | Long-only ranking; causal volume and PIT universe |
| `opening_range_breakout` | 1.1.0 | BREAKOUT | SINGLE_ASSET | 15 | default only | INTRADAY | none declared | Registered compatibility strategy; `paper_eligible=False`, excluded from paper funnel |
| `residual_momentum` | 1.0.0 | MOMENTUM | CROSS_SECTIONAL | 253 | default only | MONTHLY | `close, benchmark_close` | Long-only ranking; certified benchmark and PIT universe |
| `rsi_pullback` | 1.0.0 | MEAN_REVERSION | SINGLE_ASSET | 200 | `entry_rsi={5.0,10.0,15.0}; exit_rsi={60.0,70.0,80.0}` | DAILY | `close` | Long-only delivery; causal RSI and event-driven execution |
| `sector_relative_momentum` | 1.0.0 | MOMENTUM | CROSS_SECTIONAL | 126 | default only | MONTHLY | `close, sector` | Long-only ranking; authoritative PIT sector map |
| `time_series_momentum` | 1.0.0 | TREND | SINGLE_ASSET | 253 | `long_lookback={126,252}; short_lookback={63,126}` | MONTHLY | `close` | Long-only delivery; causal rolling windows and event-driven execution |
| `trend_following` | 1.1.0 | TREND | SINGLE_ASSET | 40 | default only | DAILY | `ema_fast, ema_slow, volatility` | Long-only delivery; causal features and event-driven execution |
| `volatility_contraction_breakout` | 1.0.0 | VOLATILITY | SINGLE_ASSET | 101 | `window={15,20,30}; contraction_quantile={0.15,0.25,0.35}` | DAILY | `close, high, volume` | Long-only delivery; lagged capacity and event-driven execution |
| `volume_confirmed_breakout` | 1.0.0 | BREAKOUT | SINGLE_ASSET | 21 | `window={20,40,55}; volume_multiplier={1.25,1.5,2.0}` | DAILY | `high, volume` | Long-only delivery; lagged volume and event-driven execution |
| `walk_forward_logistic` | 1.0.0 | MACHINE_LEARNING | CROSS_SECTIONAL | 253 | default only | MONTHLY | `close, volume` | Long-only ranking; labels must be known before prediction and PIT-safe |

### Families

- `TREND`: `donchian_trend`, `time_series_momentum`, `trend_following`
- `MEAN_REVERSION`: `bollinger_pullback`, `cross_sectional_short_term_reversal`, `mean_reversion`, `rsi_pullback`
- `MOMENTUM`: `consistent_momentum`, `cross_sectional_momentum`, `fifty_two_week_high`, `residual_momentum`, `sector_relative_momentum`
- `BREAKOUT`: `donchian_breakout`, `opening_range_breakout`, `volume_confirmed_breakout`
- `FACTOR`: `low_beta`, `low_volatility`
- `COMPOSITE`: `momentum_reversal_volatility`, `ohlcv_multi_factor`
- `VOLATILITY`: `volatility_contraction_breakout`
- `MACHINE_LEARNING`: `walk_forward_logistic`

## Parameter Budget

Only the 20 `paper_eligible` delivery strategies enter Campaign 1 selection.
The declared grids produce 74 distinct configurations: six 9-point grids,
two 4-point grids, and twelve default-only configurations. The excluded
`opening_range_breakout` would add one registry configuration but is not a
paper candidate.

| Strategy group | Configurations | Hard candidate budget |
| --- | ---: | ---: |
| Each of `bollinger_pullback`, `donchian_breakout`, `donchian_trend`, `rsi_pullback`, `volatility_contraction_breakout`, `volume_confirmed_breakout` | 9 | 9 each |
| Each of `cross_sectional_momentum`, `time_series_momentum` | 4 | 4 each |
| Each other paper-eligible strategy | 1 | 1 each |
| **Campaign total** | **74** | **74 distinct configurations** |

Every attempted configuration reserves a `ResearchTrial` before execution in
an immutable `ExperimentFamilySpec`. Failed, losing, and invalidated trials
remain recorded. A losing configuration is never retried under a new label;
any genuinely new hypothesis or budget requires a new family identity.

For a provisional three-fold expanding nested design, the registry reservation
ceiling is 74 screening reservations plus at most 222 candidate-fold
reservations, or **296 expected maximum trial records** before final evidence.
The exact family `maximum_trials` values must be registered before execution
and may only be lower if the corresponding candidate set is explicitly reduced.
FINAL OOS evaluation is not used to expand this budget or discover candidates.

## Screening Method

### Stage A: Exploratory/vectorized screening

Evaluate only the pre-registered configurations on the certified training
period. Use vectorized results to remove clearly non-viable candidates using
predefined economic and data-quality gates, not to certify promotion. Rank by
multiple measures such as net return, drawdown, turnover, trade count, and
stability; never select solely on maximum Sharpe. The screen is preliminary
and all attempted configurations count in the trial registry.

## Authoritative Validation Method

### Stage B: Event-driven backtesting

Replay every surviving configuration with the same authoritative pipeline used
by paper: causal execution-mode pricing, current marked-to-market equity,
RiskPolicy, integer share sizing, date-effective Indian costs, liquidity and
participation limits, sequential portfolio state, and reconciliation. Require
certified data and PIT lineage. Vectorized results cannot independently qualify
a candidate.

## Walk-Forward Design

### Stage C: Nested walk-forward

Use the existing `NestedWalkForwardSplitter` and `WalkForwardEvaluator` with
three expanding folds, subject to the certified data period being long enough:

- training window: at least 252 sessions after the strategy lookback;
- validation window: 63 sessions for daily strategies, or the equivalent
  available monthly observations;
- purge and embargo: the configured authoritative windows, never zeroed to
  improve a result;
- final OOS: a later, untouched period reserved before candidate selection.

Select using validation performance, plateau/neighborhood robustness, rank
stability, drawdown, turnover, and economic costs. Persist fold boundaries,
purges, embargoes, selected trial IDs, data hashes, and policy identities.
No FINAL OOS observation, return, label, or metadata is visible during this
stage.

## Robustness Requirements

### Stage D: Robustness and statistics

Require the existing robustness framework to pass before a candidate can enter
the final shortlist:

- parameter-neighborhood plateau and sensitivity checks;
- baseline and comparator checks;
- 1.0x, 1.5x, 2.0x, and 3.0x cost stress;
- liquidity, participation, slippage, and overnight-gap stress;
- deterministic PSR and registry-backed DSR;
- deterministic seeded bootstrap and Monte Carlo path checks;
- sufficient independent trades, observations, and causal evidence;
- no unresolved data, reconciliation, policy, or lineage contradiction.

Weak evidence returns `PHASE 2.10 IMPLEMENTATION READY`; it is not converted
into a pass by changing thresholds after observing results.

## Sealed FINAL OOS Policy

### Stage E: Sealed FINAL OOS

Freeze the candidate, policy, comparator, universe snapshot, data hashes,
execution identity, and statistical acceptance policy before opening FINAL OOS.
Evaluate each frozen candidate exactly once through authoritative event-driven
execution. FINAL OOS cannot be used for parameter choice, family expansion,
strategy ranking, or threshold changes. Genuine certified non-synthetic
evidence may proceed through the existing contractual acceptance path; otherwise
the verdict remains `PHASE 2.10 IMPLEMENTATION READY`.

## Portfolio Selection

### Stage F: Cross-strategy portfolio selection

Select a diversified subset only from candidates that passed the preceding
authoritative gates. Use risk-adjusted out-of-sample contribution, correlation,
turnover, capacity, sector concentration, drawdown, and cost robustness. Apply
the frozen RiskPolicy sequentially across all orders; do not select a portfolio
because it maximizes a single backtest Sharpe. Portfolio selection must not
reopen candidate parameters or FINAL OOS.

## Paper Eligibility

A strategy is eligible for the INR 100000 forward-paper account only if it is
marked `paper_eligible=True`, has certified PIT-safe lineage, passed authoritative
event-driven validation, nested walk-forward and robustness/statistical gates,
has no unresolved integrity failure, and remains compatible with the frozen
economic contract. The opening-range strategy is excluded by its registry
metadata. Paper sessions use the frozen starting capital, persist their economic
identity, perform no historical order replay, and remain blocked on
reconciliation failure or contract mismatch.

**CAMPAIGN 1 SPECIFICATION READY FOR REVIEW**
