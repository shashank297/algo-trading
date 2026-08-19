# Backtesting

Vectorized mode is screening-only. Single-asset event replay and `PortfolioEventBacktester` are authoritative for fills and order state.

Signals execute no earlier than the next eligible bar. Price channels are shifted, ranks use the synchronized eligible universe, missing OHLC rows are not forward-filled, and mixed adjustment states are rejected.

Portfolio replay converts target weights into delta orders, tracks cash/positions/average cost, and persists attribution. Defaults cap position at 5%, gross exposure at 20%, sector exposure at 10%, and participation at 5% of bar volume.

Indian delivery costs use the effective-dated `angel-nse-delivery-2026-04` schedule: Angel One delivery brokerage, STT, NSE transaction charge, SEBI fee, IPFT, GST, buy-side stamp duty, sell-side DP charge, spread, slippage, and participation impact. Rates remain configuration data and every component is persisted per fill. Execution drag is embedded in fill price but subtracted only once when net PnL is derived.

Deterministic run IDs include the input data hash, effective strategy defaults, execution mode, and cost configuration. Mass-job keys also include source and canonical market-data revisions, so changed data cannot silently reuse completed work.

Mass research performs expanding train/test walk-forward evaluation. Candidate parameters are selected on each training window; only the following test window is persisted as `OUT_OF_SAMPLE` evidence for RCA and promotion.

Fold-scoped attribution and round trips are stored separately from completed-run evidence. RCA defaults to out-of-sample metrics, costs, breadth, correlations, and explanations; in-sample loss explanations must be requested explicitly.

Single-asset event mode derives cash, holdings, fills, fees, and marked-to-market equity from bar-by-bar replay. Single-asset and cross-sectional forward paper sessions have configuration-specific identities, execute only after a newer completed bar/session, and apply position, gross-exposure, daily-loss, and drawdown limits before entry. They remain scheduled local simulations rather than broker-connected streaming sessions.
