# Phase 2.3 Tasks: Market Context + Deterministic Regime Engine

## Phase 1: Setup & Migration

- [x] T001 Create `storage/migrations/017_market_regime.sql` with `market_regime_snapshots` table and indexes.

## Phase 2: Core Domain & Market Regime Engine

- [x] T002 Create `trading_stack/market_regime.py` with domain models: `MarketContextType`, `RawMarketRegime`, `MarketRegimeFeatures`, `MarketRegimeComponentScores`, `MarketRegimeEvidence`, `MarketRegimeSnapshot`, `MarketRegimePolicy`.
- [x] T003 Implement point-in-time evidence collection in `MarketRegimeEngine` (benchmark daily/derived bars, PIT universe membership, optional India VIX) enforcing `known_at <= decision_time`.
- [x] T004 Implement causal feature extraction for trend, volatility, breadth, dispersion, liquidity, and stress in `MarketRegimeEngine`.
- [x] T005 Implement normalized continuous component scoring on $[-1.0, +1.0]$ and deterministic confidence calculation with missing evidence penalties.
- [x] T006 Implement deterministic decision tree for raw market regime classification (`BULL_LOW_VOL`, `BULL_HIGH_VOL`, `SIDEWAYS_LOW_VOL`, `SIDEWAYS_HIGH_VOL`, `BEAR_HIGH_VOL`, `RECOVERY`, `INSUFFICIENT_CONTEXT`).

## Phase 3: Storage Layer Integration

- [x] T007 Add `persist_market_regime_snapshot()`, `get_market_regime_snapshot()`, and `list_market_regime_snapshots()` to `storage/duckdb_manager.py`.

## Phase 4: Public API & CLI Integration

- [x] T008 Update `trading_stack/__init__.py` to export market regime classes and engine.
- [x] T009 Add `--command market-regime` with `--as-of`, `--context`, and `--decision-time` arguments to `research.py`.

## Phase 5: Tests

- [x] T010 Create `tests/test_market_regime_migration.py` testing fresh DB migration 017 and incremental upgrade from 016.
- [x] T011 Create `tests/test_market_regime.py` testing all 7 synthetic regimes, component scoring, confidence, and no-strategy-selection invariant.
- [x] T012 Create `tests/test_market_regime_pit.py` testing point-in-time causality: future close mutation, future intraday bar mutation, future universe member exclusion, future VIX mutation, holiday handling, and EOD vs Intraday separation.
- [x] T013 Create `tests/test_market_regime_cli.py` testing CLI invocation and output formatting.

## Phase 6: Documentation

- [x] T014 Create `docs/market_regime.md` detailing taxonomy, feature definitions, scoring scales, PIT semantics, and usage.

## Phase 7: Full Repository Verification & CI

- [ ] T015 Run full local validation: pytest, ruff, mypy, pyright, compileall, coverage (global >= 80%, critical >= 95%), pip-audit, frontend lint/build.
- [ ] T016 Commit directly to `main` with descriptive message and push to `origin/main`.
- [ ] T017 Monitor and verify GitHub Actions CI run on exact pushed `main` SHA until all 6 matrix jobs are 100% green.
