# Phase 2.8-2.10 Adaptive Selector

The adaptive selector is itself a strategy and is validated as a continuous causal portfolio process.

## Scorecards

- Strategy scorecards separate mandatory eligibility from ranking.
- Mandatory failures such as missing lineage, DQ/PIT/OOS failure, insufficient evidence, excessive drawdown, failed cost stress, failed robustness, or capacity failure make the scorecard `INELIGIBLE`.
- `INELIGIBLE` scorecards receive `overall_score = 0` and cannot be selected or ensembled.
- Eligible scorecards use bounded component scores and bounded penalties for drawdown, turnover, correlation, capacity, and uncertainty.
- Scorecard hashes bind the Phase 2.7 evidence hash, policy hash, lineage IDs, policy version, and `available_at`.

## Selector

- The selector emits intent only: `SELECT`, `ENSEMBLE`, or `ABSTAIN`.
- It never sends broker, live, paper, or portfolio execution orders.
- Every consumed scorecard must satisfy `available_at <= decision_time`; future evidence is rejected or excluded.
- `ABSTAIN` is normal behavior for no eligible strategy, stale/insufficient evidence, low regime confidence, unclear asset state, weak net edge, high uncertainty, or switch costs that erase benefit.
- Hysteresis preserves an eligible incumbent unless challenger advantage exceeds the switch buffer, estimated switch cost, and uncertainty margin.
- Ensembles are built only from independently eligible strategies and filter highly correlated strategy families.

## Meta Replay

- Historical replay walks decision time by decision time through regime, asset state, available scorecards, selector decision, hysteresis, target portfolio, portfolio delta, costs, and portfolio state.
- Portfolio state is continuous across strategy changes; switches trade only deltas rather than resetting holdings.
- Risk-reducing sells are identified before buys in switch-cost estimates.
- Replay metrics include returns, CAGR, volatility, Sharpe, Sortino, Calmar, drawdown, VaR/CVaR, turnover, costs, switching drag, switch count, dwell, regime transitions, and abstentions.
- Baselines are reported as B0 benchmark, B1 cash, B2 static training-only winner, B3 equal eligible ensemble, B4 simple diversified ensemble, and B5 adaptive.

## Validation

- Meta train, validation, and final OOS split boundaries are explicit and include purge/embargo configuration.
- The final verdict may accept the adaptive selector or report `ADAPTIVE_COMPLEXITY_NOT_JUSTIFIED` when simpler baselines win after costs.
- Stress reports include base cost, 1.5x cost, 2.0x cost, switch-cost stress, delayed execution, and reduced liquidity.
- Read-only inspection commands in `research.py` query historical scorecards, selector decisions, and meta runs with explicit cutoffs and no latest fallback.

Phases 2.11 and later remain out of scope.
