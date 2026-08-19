# Risk Management

The default paper policy caps a position at 5% of capital, gross exposure at 20%, daily loss at 1%, and drawdown at 5%. The independent `RiskEngine` returns `PASS`, `MODIFY`, or `REJECT` and records reasons in DuckDB.

Strategy code and agents may propose an order but cannot override this policy. Paper sessions apply risk checks before persistence. Configuration validation rejects any value other than `research.live_trading: false`, and no live execution adapter exists.

Cross-sectional replay additionally caps sector exposure at 10%, applies volume participation and minimum-liquidity checks, and preserves non-negative cash. Promotion uses out-of-sample metrics and correlation-cluster independence; only a human-approved validated run can become a paper candidate.

Promotion also requires at least three walk-forward folds, positive performance in 60% of folds, stable parameter selection, positive PnL after doubling recorded costs, and broad portfolio contribution. When another strategy is already paper-approved, missing OOS correlation evidence is a rejection rather than assumed diversification.
