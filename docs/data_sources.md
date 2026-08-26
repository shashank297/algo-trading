# Data Sources & Price Adjustments

## 1. Provider Ecosystem

- **Angel One SmartAPI**: Primary ingestion source for Indian equity (NSE) market data. `AngelOneProvider` wraps the historical and streaming client.
- **DuckDB Cache**: Local storage (`market_data.duckdb`) serving canonical, validated market datasets.
- **OpenBB HTTP Adapter**: Optional adapter communicating with a separately running OpenBB API instance.

Every stored dataset record tracks immutable data lineage including `provider_name`, `symbol`, `canonical_symbol`, `exchange`, `timeframe`, `retrieved_at`, `timezone`, `declared_adjustment`, `adjustment`, `raw_hash`, `transformation_hash`, `status`, and `lifecycle_status`.

---

## 2. Canonical Price Basis & Corporate Actions Engine (P0-1)

- **Default Basis**: Split-adjusted price data (`SPLIT_ADJUSTED`) is the authoritative default across all research, vectorized screening, event-driven backtesting, and forward paper trading.
- **PriceAdjustmentEngine**: Automatically detects corporate action announcements (splits, consolidations, bonuses, and dividends) from `corporate_actions` table records and computes backward-adjusted OHLCV price series.
- **Lineage Verification**: Research datasets track `source_basis` (raw input), `canonical_basis` (persisted dataset), and `research_basis` (adjusted research frame). Backtests strictly reject mixed adjustment states.
- **Discontinuity Detection**: The engine validates observed raw price transitions against expected split ratios, raising warnings if provider history is already adjusted or discordant.

---

## 3. Point-in-Time Universe Isolation (P0-4)

- **Snapshot Ingestion**: `main.py --universe-snapshot SNAPSHOT_ID --benchmark NIFTY200` ingests daily history for all verified constituent members.
- **Point-in-Time Masking**: `SynchronizedPanelBuilder` applies constituent membership intervals to ensure stocks are only eligible for ranking during dates they actively belonged to the index.
- **No Lookahead**: Newly listed constituents are never backfilled with synthetic or fabricated pre-listing prices. They become eligible only after their causal strategy lookback window is reached.

---

## 4. History Backfill & Quality Revalidation

- **Resumable Backfill**: `tools/backfill_market_history.py` downloads multi-timeframe (`1d`, `1m`) history back to the configured start date. Earliest available provider timestamps are authoritative; missing pre-listing data is never manufactured.
- **Quality Revalidation**: `tools/revalidate_historical_datasets.py` and `tools/refresh_session_quality.py` verify datasets offline against the official, versioned NSE trading calendar without modifying candle observations.
- **Exact DQ Certification**: Datasets must pass the 6 mandatory zero-issue checks (`schema`, `ohlc_integrity`, `duplicates`, `session_alignment`, `missing_sessions`, `timestamp_integrity`) to become `CERTIFIED` and eligible for research frame construction.
