# Data Sources

Angel One remains the configured India source. `AngelOneProvider` wraps the existing historical client; `DuckDBCacheProvider` serves canonical local data; `OpenBBHttpProvider` is optional and communicates with a separately running OpenBB API backend.

Every new snapshot stores provider, provider symbol, canonical symbol, exchange, timeframe, retrieval time, timezone, adjustment state, raw hash, transformation hash, and metadata. Failed fallback attempts are also recorded.

Angel One prices are `UNADJUSTED` unless a verified provider supplies adjusted data. Backtests reject mixed adjustment states. Configure provider priority and the optional `research.openbb_base_url` in `config/config.yaml`.

NIFTY 200 snapshot ingestion uses `main.py --universe-snapshot SNAPSHOT_ID --benchmark NIFTY200`.
It downloads daily history for every eligible member, resolves the exact `AMXIDX` NIFTY 200 token,
uses the latest completed NSE session as the daily cutoff, and repairs expected internal gaps with
an overlapping fetch window. Newly listed constituents are never backfilled with invented prices;
they become rank-eligible only after the strategy's causal lookback is available.

`tools/backfill_market_history.py` requests both timeframes back to the configured date, but availability is evidence-driven. Current Angel One minute tokens commonly stop near a provider/token boundary rather than 2012. The stored per-symbol minimum timestamp is authoritative; missing pre-boundary candles are never synthesized.

`tools/refresh_session_quality.py` recomputes session-alignment evidence offline against the configured, versioned NSE calendar. It does not fetch, alter, or delete candles. Out-of-session observations remain research blockers until an exchange event is evidenced or the observation is quarantined through a reviewed data-quality process.
