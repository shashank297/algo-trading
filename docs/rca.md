# Root-Cause Analysis and Promotion

Single-asset and portfolio fills both populate `trade_attribution`. Evidence includes run ID,
symbol, side, reason, quantity, price, average cost, gross and realized PnL, execution cost, entry
timestamp, holding period, and exit classification. Correlation records identify each side by full
run ID and symbol, avoiding ambiguous same-strategy comparisons across stocks.

```bash
python research.py --command rca --run-ids RUN_ID_1,RUN_ID_2,RUN_ID_3
python research.py --command promote --run-id RUN_ID
python research.py --command promote --run-id RUN_ID --paper-approved
```

RCA uses out-of-sample net returns and records return correlation, signal/trade overlap, holdings overlap, drawdown overlap, regime correlations, clusters, and effective independent bets. Symbol/reason and sector attribution explain losses and cost drag.

Promotion requires out-of-sample evidence, minimum risk-adjusted metrics, bounded drawdown, trade breadth, and independence. Human approval is required for `PAPER_CANDIDATE`. `--paper-activate` may move an eligible candidate to `PAPER_ACTIVE`; it cannot enable live trading.
