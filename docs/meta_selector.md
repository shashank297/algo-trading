# Phase 2.8-2.10 Adaptive Selector

The adaptive selector is itself a strategy and is validated as a continuous causal portfolio process.

## Scorecards

- Strategy scorecards separate mandatory eligibility from ranking.
- Mandatory inputs are tri-state: missing evidence and failed evidence both make the scorecard `INELIGIBLE`, but are persisted as distinct forensic reasons.
- Scorecard `available_at` is an explicit timezone-aware materialization timestamp supplied by research orchestration, never inferred from current time or upstream Phase 2.7 evidence time.
- Scorecard materialization must not predate any upstream evidence availability.
- `INELIGIBLE` scorecards receive `overall_score = 0` and cannot be selected or ensembled.
- Eligible scorecards use bounded component scores and bounded penalties for drawdown, turnover, correlation, capacity, and uncertainty.
- Scorecard hashes bind the Phase 2.7 evidence hash, policy hash, lineage IDs, policy version, and `available_at`.

## Selector

- The selector emits intent only: `SELECT`, `ENSEMBLE`, or `ABSTAIN`.
- It never sends broker, live, paper, or portfolio execution orders.
- Every consumed scorecard must satisfy `available_at <= decision_time`; future scorecards/evidence are invisible to the complete historical decision object and hash.
- `ABSTAIN` is normal behavior for no eligible strategy, stale/insufficient evidence, low regime confidence, unclear asset state, weak net edge, high uncertainty, or switch costs that erase benefit.
- Hysteresis preserves an eligible incumbent unless challenger advantage exceeds the switch buffer, estimated switch cost, and uncertainty margin.
- Ensembles are built only from independently eligible strategies with available pairwise RCA/correlation evidence; missing correlation evidence can only produce `SELECT` or `ABSTAIN`.

## Meta Replay

- Historical replay walks decision time by decision time through regime, asset state, available scorecards, selector decision, hysteresis, target portfolio, portfolio delta, isolated historical execution, costs/slippage, and portfolio state.
- The adaptive B5 path must not use a synthetic `selected_return - switching_cost` shortcut; equity comes from cash, holdings, fills/costs, and realized historical asset returns.
- `ABSTAIN` behavior is explicit and policy-versioned as `HOLD_CURRENT`, `REDUCE_RISK`, or `CASH`.
- Portfolio state is continuous across strategy changes; switches trade only deltas rather than resetting holdings.
- Risk-reducing sells are processed before buys in historical rebalance deltas.
- Replay metrics include returns, CAGR, volatility, Sharpe, Sortino, Calmar, drawdown, VaR/CVaR, notional turnover, costs, slippage, switching drag, switch count, dwell, regime transitions, abstention duration/returns, skipped opportunities, risk avoided, and drawdown effect.
- Baselines are reported as B0 benchmark, B1 cash, B2 static training-only winner, B3 equal eligible ensemble, B4 simple diversified ensemble, and B5 adaptive.

## Validation

- Meta train, validation, and final OOS split boundaries are explicit and include purge/embargo enforcement.
- Meta-selector trials must be registered before the first final-OOS observation is consumed; final-OOS results cannot be reported for retrospectively registered policies.
- The final verdict may accept the adaptive selector or report `ADAPTIVE_COMPLEXITY_NOT_JUSTIFIED` when simpler baselines win after costs.
- Stress reports rerun historical execution for base cost, 1.5x cost, 2.0x cost, switch-cost stress, delayed execution, and reduced liquidity.
- Read-only inspection commands in `research.py` query historical scorecards, selector decisions, and meta runs with explicit cutoffs and no latest fallback.

Phases 2.11 and later remain out of scope.
