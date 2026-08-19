# Production Readiness

Audit date: 2026-08-18

Current decision: **READY for NIFTY 200 daily historical research; CONDITIONALLY READY for forward paper trading after out-of-sample promotion approval; NOT READY for minute research or live trading.**

The deterministic research stack is operational. Live order routing remains unavailable by design.

## Verified

- SmartAPI authentication succeeds and logs only a masked client identifier.
- Instrument-master refresh loaded 155,535 records.
- Daily Angel One history is available for all 200 members of snapshot `NIFTY200_2026_08_17` through the latest completed session.
- The exact NIFTY 200 index benchmark is stored as `NIFTY200` with 1,644 daily bars from 2020-01-02 through 2026-08-17.
- Universe readiness passes with 200 provider tokens, 200 symbols with data, 194 symbols with at least 253 bars, and zero unresolved calendar-alignment exceptions.
- Six newly listed members have 162-209 available bars and remain ineligible until each strategy's lookback is satisfied.
- A full authoritative cross-sectional momentum replay completed across the snapshot in 709.5 seconds with 5,145 fills, 163 persisted rebalances, and 2,798 reconciled round trips. This is in-sample evidence only.
- DuckDB contains no duplicate candle keys, invalid OHLC rows, or null core candle fields.
- Strategy discovery exposes 20 paper-eligible strategies plus inactive opening-range-breakout compatibility.
- Vector, event, experiment, mass-research, walk-forward, RCA, promotion, and paper CLI paths execute.
- Single-asset and synchronized portfolio paper runs have distinct IDs, process forward-only bars, apply independent risk gates, and reconcile approved fills.
- Run and resumability identities include effective parameters, execution mode, cost configuration, source revision, and canonical market-data revision.
- Single-asset, portfolio, and forward-paper event paths use the versioned Indian delivery schedule for authoritative fills.
- Forward-paper state, pending targets, orders, fills, costs, attribution, and reconciliation commit atomically.
- Trade-level gross PnL reconstructs reference-price performance; net PnL subtracts each reported cost exactly once.
- Expanding walk-forward folds select bounded parameters on training data and persist test-only out-of-sample evidence.
- Mass jobs retry within their configured budget; abandoned and superseded jobs are recovered or cancelled explicitly.
- Archive export retains canonical rows by default and verifies Parquet row count before any explicit purge.
- Live trading is not implemented and cannot be enabled through configuration.
- Backup, SHA-256 verification, and atomic restore are implemented. A 4,053,020,672-byte production-sized backup with 48 tables and 24,431,417 candles was restored and opened successfully.
- Linux/Windows CI covers Python 3.12, with a Python 3.13 Linux lane, Ruff, mypy, coverage, dependency audit, and secret scanning.
- The local gate passes 101 tests, compilation, Ruff, strict mypy across 57 source files, 78% branch-aware coverage, and a clean dependency audit.

## Release Blockers

### Market Data

- The official NIFTY 200 snapshot is current-constituent metadata and therefore survivorship-biased.
- New provider and historical-backfill imports retain immutable observations, dataset hashes, provider attempts, adjustment state, and canonical dataset IDs. Pre-upgrade legacy candles still lack complete retrieval-time lineage.
- Prices are unadjusted. Corporate actions and total-return adjustment are unavailable.
- Exchange special sessions and exceptional closures are versioned overrides; future dates still require operator verification against NSE circulars.
- Isolated no-data periods remain for suspended or renamed securities and are excluded per date rather than price-filled.
- The full NIFTY 200 minute backfill is resumable but remains subject to Angel One retention/token boundaries. Reports must state each symbol's observed minimum timestamp; no 2012 minute claim is allowed where the provider begins later.
- Angel One minute data observed during backfill ends at 15:28 for the latest completed session. This is recorded as a provider limitation rather than filled synthetically.
- Minute readiness currently has data for 69/200 members, no minute benchmark, and 1,461 out-of-session observations under calendar evidence version `2026.08.18.3`. Legitimate exceptional sessions must be modeled and suspect timestamps quarantined before minute research is enabled.

### Execution And Paper Trading

- Single-asset event mode is a fill-driven cash-and-position replay, while vector mode remains screening-only.
- Forward paper state and pending targets are transactional in DuckDB, and approved single/portfolio sessions advance only after successful scheduled ingestion. Operation is still polling-based rather than streaming.
- Full-universe authoritative replay currently takes about twelve minutes per strategy/parameter run. Phase and 500-session progress events are emitted, but profiling is required before large research matrices.
- No broker sandbox reconciliation exists against independently observed fills.

### Research And RCA

- RCA correlation and promotion joins use stable run IDs; display labels remain descriptive only.
- The bounded walk-forward evaluator retrains/selects per fold, but broad parameter matrices still need compute profiling and multiple-comparison controls.
- Historical membership, delisted securities, and point-in-time sector classifications are unavailable.

### Agents And Orchestration

- Task deadlines return control before a blocked callable completes, and OpenAI HTTP calls receive the configured timeout.
- Real OpenAI workflows fail closed until explicit input/output model pricing is configured; token and USD budgets are then enforced and audited.
- No paid production agent call was made during this audit. The fake-client workflow is covered by deterministic tests.

### Operations

- Git does not recognize the workspace's `.git` directory. Experiments correctly use a source-tree hash fallback, but commit-based release provenance is unavailable.
- The local production-sized restore drill passes. Off-machine backup retention, a formal recovery-time objective, and migration rollback remain operational work.
- DuckDB is intentionally single-writer. Two-worker mass research has passed deterministic integration testing, but sustained load profiling is still required.
- Quality findings are separated into `CRITICAL`, `ERROR`, and `WARNING`; external alert delivery is not configured.

## Required Go-Live Sequence

1. Add corporate-action adjustment and point-in-time universe data.
2. Backfill immutable retrieval provenance for pre-upgrade legacy candles where source evidence is available.
3. Profile and optimize full-universe event replay before running large parameter matrices.
4. Add an independently observed broker sandbox/streaming paper feed before claiming execution parity.
5. Establish off-machine backups and rehearse a production-sized restore against a documented RTO.
6. Run several weeks of monitored paper trading and RCA review. Live routing remains out of scope.
