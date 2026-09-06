# Risk Management

The single authoritative source for portfolio risk limits is the canonical versioned risk policy defined in [`config/risk_policy.yaml`](file:///c:/Python%20projects/algo%20trading/config/risk_policy.yaml), formally approved under Human Board Decision FAB-31 (Policy Version `1.1.0`, Policy Hash `9839425d1c770c2b25744b110122c7b44cd3d7e4ee0e94dbb942dfa07f9d2092`).

## Canonical Risk Parameters

The platform enforces the following exact Board-approved limits:

| Risk Parameter | Field | Limit | Units | Description |
|---|---|---|---|---|
| **Max Position Concentration** | `max_position_pct` | 5% (0.05) | Fraction of capital | Single-stock exposure cap |
| **Max Gross Portfolio Exposure** | `max_gross_exposure_pct` | 100% (1.00) | Fraction of capital | Long-only cash equity cap; >100% rejected |
| **Max Daily Portfolio Loss** | `max_daily_loss_pct` | 1% (0.01) | Fraction of capital | Daily loss circuit breaker |
| **Max Portfolio Drawdown** | `max_drawdown_pct` | 5% (0.05) | Fraction of capital | Cumulative peak-to-trough drawdown halt |
| **Max Sector Exposure** | `max_sector_exposure_pct` | 20% (0.20) | Fraction of capital | Industry sector allocation cap |
| **Max Open Positions** | `max_open_positions` | 20 | Count | Simultaneous instrument holding cap |
| **Max 1-Day 95% VaR** | `max_var_pct` | 2% (0.02) | Fraction of capital | Daily parametric/historical portfolio VaR cap |
| **Minimum Daily Liquidity** | `min_liquidity_crore` | ₹5.0 Cr (5.0) | Crores ADTO | Minimum median daily turnover requirement |

### Interpretation of Gross Exposure Limit

`max_gross_exposure_pct = 1.00` permits at most 100% gross exposure for the current long-only portfolio. It does **NOT** authorize:
- leverage
- margin borrowing
- short exposure
- derivatives leverage
- gross exposure above 100%
- live capital deployment

The approved policy is intended for research validation and forward paper trading only.

## Fail-Closed Architecture

The independent [`RiskEngine`](file:///c:/Python%20projects/algo%20trading/risk/engine.py) returns `PASS`, `MODIFY`, or `REJECT` and records structured decisions in DuckDB. Authoritative research, backtesting, and paper-trading workflows strictly fail closed:

- **Missing canonical policy:** BLOCK
- **Invalid canonical policy:** BLOCK
- **Policy hash mismatch:** BLOCK
- **Unknown required field:** BLOCK
- **Runtime override on authoritative/paper path:** BLOCK
- **Silent fallback to unconfigured defaults:** BLOCK

Strategy code and AI agents may propose an order via `TradeProposal` but cannot override the canonical policy. Paper sessions apply canonical risk checks prior to order execution and persistence. Configuration validation rejects any value other than `research.live_trading: false`, and no live execution adapter exists (`CAN_DEPLOY_REAL_CAPITAL = False`).

Cross-sectional replay additionally applies volume participation and minimum-liquidity checks, and preserves non-negative cash. Promotion uses out-of-sample metrics and correlation-cluster independence; only an externally human-approved validated run bound to the canonical risk policy hash can become a paper candidate.
