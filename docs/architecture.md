# Architecture

This is the single authoritative architecture document for the platform (it previously
existed as three overlapping/duplicate documents — `docs/architecture.md`,
`docs/current-architecture.md`, and an unlabeled "Architecture" section appended to this
file — which have been merged here to remove drift between them).

## 1. Current Architecture

### Working components

`main.py` loads configuration, authenticates to Angel One, refreshes the instrument master,
fetches historical candles, stores canonical data in DuckDB, runs data-quality checks, and
writes reports. `scheduler.py` invokes that ingestion path on a local schedule.

`smartapi/` is the only real market-data integration. `storage/DuckDBManager` owns schema
setup, candle upserts, and audit logs. `validators/` checks missing candles, duplicates,
timestamps, nulls, and OHLC integrity.

`trading_stack/` adds feature generation, candle-based strategies, vector screening, event
replay, and paper-fill simulation. `research.py` is the local research CLI.

### Current flow

```text
Angel One -> SmartAPI clients -> validation -> historical_candles -> features
-> strategy -> vector or event backtest -> run/order/fill records
```

### Preserved boundaries

- Angel One authentication, fetching, data-quality validation, DuckDB tables, and scheduled
  ingestion remain in place.
- `historical_candles` remains the compatibility cache used by existing readers.
- The platform remains local-first and has no live order route.

### Design boundaries & constraints

- **Local persistence only**: DuckDB (`market_data.duckdb`) is the only persistence layer. It
  is a single-writer file, meaning multi-process ingestion and research jobs must be
  orchestrated carefully.
- **No live trading**: Live order routing remains entirely unavailable by design. The
  environment is strictly for deterministic backtesting and paper simulation.
- **Agent sandboxing**: AI research agents receive stored evidence and constrained tool
  results only. No LLM can access credentials, run broker actions, or autonomously promote a
  strategy to live paper states.
- **Immutable provenance**: Every fulfilled request comes from exactly one provider snapshot;
  vendor data is never blended synthetically.

## 2. Target Architecture

```text
User / CLI
  -> local task orchestrator
  -> data platform -> DuckDB cache and immutable dataset provenance
  -> synchronized features -> single-asset fan-out / cross-sectional ranking
  -> vector screening / authoritative portfolio event replay
  -> walk-forward evidence -> RCA clusters -> deterministic risk -> paper broker

Research Manager
  -> Technical Analyst + Quant Analyst -> Risk Analyst -> structured synthesis
```

Data, strategy, risk, and execution have separate packages. Research agents receive stored
evidence and constrained tool results only. The paper broker shares the order and risk
contracts used by event replay. Broker credentials remain outside every agent process.

Initial provider order is DuckDB cache, Angel One, then optional OpenBB HTTP. Each fulfilled
request comes from exactly one provider snapshot; vendor data is never blended.

## 3. Production Research Slice (implemented target-state detail)

The NIFTY 200 workflow uses immutable official constituent snapshots. `UniverseResearchService`
requires exactly 200 active members, provider tokens, strategy lookback coverage, and an approved
benchmark series before a snapshot-scoped portfolio experiment can start. Exact benchmarks and
operator-approved proxies are stored separately; proxies are never selected silently.

Cross-sectional strategies consume one UTC-normalized synchronized panel, rank only symbols that
are eligible on each date, and execute target-weight deltas on the next eligible session.
`PortfolioEventBacktester` remains authoritative for fills, cash, exposure, turnover, statutory
costs, liquidity rejection, and attribution.

Paper trading is forward-only for both strategy scopes. The first invocation creates a persisted
watermark and queues the latest single-symbol target or synchronized portfolio targets without
creating orders. Later invocations may execute only after a newer completed market-calendar bar or
common session is stored. Historical replay remains an event-backtest capability.

All entrypoints write the readable application log plus `logs/events_YYYY-MM-DD.jsonl`. Structured
records include component, command, operation ID, level, timestamp, and message.

The platform extends Angel One ingestion while preserving the existing no-argument `main.py` and
scheduler behavior. An optional `--universe-snapshot` flag lets ingestion read an immutable,
eligible symbol set from DuckDB. DuckDB remains the only persistence layer and live order routing
remains unavailable.

### Research flow

```text
provider snapshots -> synchronized dataset -> causal features
  -> SINGLE_ASSET fan-out or CROSS_SECTIONAL ranking
  -> vector screening or authoritative event replay
  -> expanding walk-forward evidence
  -> RCA correlation clusters and promotion review
  -> human-approved paper broker
```

`SINGLE_ASSET` produces one run per stock. `CROSS_SECTIONAL` ranks a synchronized universe and
produces one portfolio run with child positions, rebalances, costs, and symbol attribution.

Signals use `timestamp`, `symbol`, `target_weight`, `signal`, `reason`, `score`, `rank`, and
`feature_snapshot`. Existing strategies retain `target_position` for compatibility.
Auto-discovery is restricted to `trading_stack.strategy_library`.

Cross-sectional signals execute on the next stored NSE session. Portfolio replay converts target
weights into delta orders, processes sells before buys, maintains cash and average cost, caps
position/gross/sector exposure, and applies liquidity-based partial fills or rejection.

Mass jobs hash strategy/version, scope, universe, parameters, cost version, walk-forward sizes,
and source revision. Successful jobs are skipped on rerun. RCA compares out-of-sample net returns,
holdings, trades, and drawdowns so correlated strategies do not count as independent evidence.

No LLM can access credentials, run broker actions, or promote a strategy. `LIVE_READY` is
documentation-only; deterministic automation stops at `PAPER_ACTIVE`.

See `docs/production_readiness.md` for verified runtime status and remaining release blockers.
Forward paper sessions persist state and risk decisions, but still require scheduled ingestion
and are not a broker-connected streaming service.

## Integration opportunities

- `data_platform/` isolates providers and captures immutable data lineage.
- `experiments/`, `risk/`, and `orchestration/` add reproducibility and auditability without
  distributed infrastructure.
- `ai_research/` can interpret recorded evidence but cannot fabricate calculations or execute
  trades.
