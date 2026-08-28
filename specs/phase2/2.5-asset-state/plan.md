# Phase 2.5 Implementation Plan

1. Define typed policies, feature/evidence contracts, eligibility, clusters, snapshots, a pure engine,
   and an authoritative storage-backed service in `trading_stack/asset_state.py`.
2. Reuse `PointInTimeUniverseManager` and `DuckDBManager.load_regime_bars()` for PIT membership and
   certified stock/benchmark admission; independently enforce causal timestamps and D-1 intraday input.
3. Add migration 021 and immutable DuckDB snapshot persistence, retrieval, listing, replay, and conflict handling.
4. Export the public contracts, document policy configuration, and include the core module in critical coverage.
5. Certify cluster boundaries, optional metadata, causality, evidence identity, eligibility, restart/readback,
   storage integration, and all pre-existing Phase 2.1–2.4 invariants.

