# Technical Research: Final Audit Remediation

## 1. P0-3: OpeningTickObservation & Receipt-Time Causality

- **Decision**: Define `OpeningTickObservation` as a frozen dataclass with mandatory `symbol`, `exchange`, `token`, `price`, `exchange_timestamp` (timezone-aware), `received_at_utc` (timezone-aware), and `quality_state`.
- **Rationale**: Guarantees true physical receipt-time ordering. Fills must execute strictly at `received_at_utc` because exchange timestamp represents when the venue matched the trade, not when our gateway observed it.
- **Alternatives Considered**: Using `timestamp` single field. Rejected because it conflates exchange clock with local observation clock and introduces lookahead bias in backtests and forward paper trading.
- **Validation**: Enforce `received_at_utc >= exchange_timestamp`, `price > 0`, non-negative sequence numbers and stream epochs.

## 2. P1-9 & E-10: Exact Lineage & Authoritative DQ Binding

- **Decision**: In `SynchronizedPanelBuilder` and `StrategyPipeline.load_candles`, extract contributing dataset IDs directly from row-level candle metadata. For each dataset, verify that `data_quality_certifications` contains an exact record whose `dataset_content_hash` matches the dataset's current `transformation_hash` with exactly 6 zero-issue child checks in `quality_report`.
- **Rationale**: Eliminates `ORDER BY completed_at DESC LIMIT 1` and `_latest_dataset_id()`, preventing an unrelated newer dataset or newer certification from validating an older snapshot.
- **Alternatives Considered**: Storing only a single composite hash without dataset IDs. Rejected because granular auditability requires tracing each symbol's exact slice back to its canonical provider batch.

## 3. E-8: Stream Gap Recovery & Aggregator State Machine

- **Decision**: In `SmartAPIWebSocketClient`, sequence discontinuities immediately trigger `DEGRADED` state and persist an `UNREPAIRED` gap record with actual `gap_size`. The client increments its generation ID and initiates a fresh socket connection. In `RealtimeBarAggregator`, `close_degraded_interval(symbol, reanchor_time)` closes the open-ended degraded interval at re-anchor while retaining the historical gap interval as untrusted.
- **Rationale**: Replaying subscriptions on the same degraded socket violates protocol safety. A fresh generation guarantees a clean stream state, and closing the open-ended degraded interval allows subsequent real-time bars to form reliably while protecting against the missed historical window.

## 4. E-10 & Promotion: Out-of-Sample Metric Evaluation

- **Decision**: `PromotionEngine` must evaluate strategy performance (Sharpe ratio, Max Drawdown) from stitched out-of-sample equity returns stored in `strategy_equity_curve` (`evidence_level = 'OUT_OF_SAMPLE'`), rather than averaging fold metric values (`AVG(metric_value)`).
- **Rationale**: Averaging Sharpe ratios across folds produces mathematically invalid composite Sharpe and masks compounding sequence-of-returns drawdowns across regime transitions.

## 5. Vectorized Cost Schedule Parity

- **Decision**: Update `StrategyPipeline.run(mode='vectorized')` to instantiate `VectorizedBacktester(cost_model=cost_schedule)` with the configured `IndianDeliveryCostSchedule`.
- **Rationale**: Ensures vectorized screening reports net PnL accounting for statutory charges, STT, exchange fees, and slippage.
