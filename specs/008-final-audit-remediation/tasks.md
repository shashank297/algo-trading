# Tasks: Final Audit Remediation & Institutional Hardening

**Feature**: Final Audit Remediation
**Directory**: `specs/008-final-audit-remediation`
**Status**: In Progress

## Phase 1: Foundation & Database Schema Migrations

- [ ] Task 1.1: Create SQL migration `010_exact_frame_evidence_and_gap_recovery.sql` ensuring `research_frame_certifications` and `stream_gaps` contain all required columns.
- [ ] Task 1.2: Verify migration runner executes cleanly on `market_data.duckdb` and temporary test databases.

## Phase 2: User Story 1 — P0-3: TRUE_NEXT_OPEN Causality & Strict Identity

- [ ] Task 2.1: Enhance `OpeningTickObservation` in `trading_stack/domain.py` with explicit timezone-aware `exchange_timestamp` and `received_at_utc`, strict validation (`received_at_utc >= exchange_timestamp`, non-negative sequence/epoch), and read-only compatibility properties.
- [ ] Task 2.2: Update `ForwardPaperSessionEngine._execute_pending` in `trading_stack/paper.py` to enforce strict instrument identity (symbol, exchange, token with fallback DB lookup if token missing on candle), execute at `received_at_utc`, record source metadata in fill payload, and reject non-TRUSTED / missing observations without historical open fallback.
- [ ] Task 2.3: Update `ForwardPortfolioPaperSessionEngine` in `trading_stack/portfolio_paper.py` and `PortfolioEventBacktester._rebalance` in `trading_stack/portfolio.py` to require `opening_observations` for `TRUE_NEXT_OPEN` mode, execute at `received_at_utc`, and reject orders with missing/degraded tick observations.
- [ ] Task 2.4: Add comprehensive adversarial unit tests in `tests/test_causality_and_invariants.py` covering missing receipt timestamps, token mismatch, exchange mismatch, DEGRADED observation, receipt timestamp fill causality, and lack of historical open fallback.

## Phase 3: User Story 2 — P1-9: Exact DQ / Research Frame Lineage

- [ ] Task 3.1: Update `ResearchDataset` in `trading_stack/datasets.py` to include `contributing_dataset_ids`, `dq_certification_ids`, `dataset_content_hashes`, `frame_certification_id`, and `pit_evidence_hash`.
- [ ] Task 3.2: Update `SynchronizedPanelBuilder.build()` in `trading_stack/datasets.py` to derive contributing dataset IDs from candle rows, verify `VERIFIED` and `CANONICAL_PROMOTED` dataset status, bind exact matching DQ certifications (validating non-empty validator version, content hash match, and exactly 6 zero-issue child checks), persist complete frame evidence, and preserve all evidence in the cache path.
- [ ] Task 3.3: Update `StrategyPipeline.load_candles()` in `trading_stack/pipeline.py` to enforce the identical exact DQ binding and persist `dataset_evidence_json` and `dq_certification_ids_json` on single-asset research frame certifications.
- [ ] Task 3.4: Update automatic repair ingestion in `main.py` to re-resolve the post-repair canonical dataset ID before running and persisting DQ certification.
- [ ] Task 3.5: Ensure `strategy_runs.frame_certification_id` is populated across both single-asset and portfolio execution flows in `storage/duckdb_manager.py`.

## Phase 4: User Story 3 — E-8: Stream Gap Recovery & Aggregator State Machine

- [ ] Task 4.1: Update `SmartAPIWebSocketClient` in `smartapi/websocket_client.py` to calculate actual `gap_size`, persist `UNREPAIRED` gap records with stream epoch, transition connection/token to `DEGRADED`, quarantine degraded ticks, and force reconnection on a new generation upon sequence drops.
- [ ] Task 4.2: Update `RealtimeBarAggregator` in `trading_stack/live_aggregator.py` to add `close_degraded_interval(symbol, reanchor_time)` to close open-ended untrusted intervals at re-anchor while retaining historical gaps, and `repair_gap(symbol, from_time, to_time)` for explicit historical repair.
- [ ] Task 4.3: Update `main.py` stream event handlers to close the aggregator's degraded interval upon stream re-anchoring, and update `data_platform/live_admission.py` to reject non-TRUSTED events.
- [ ] Task 4.4: Add stream recovery integration tests in `tests/test_stream_gap_recovery.py` covering sequence gaps, gap size persistence, degraded tick isolation, socket generation re-anchoring, and interval closure.

## Phase 5: User Story 2 & 4 — E-10: Exact Certification & Promotion Engine

- [ ] Task 5.1: Refactor `RunCertificationService` in `trading_stack/certification.py` to eliminate all `LIMIT 1` and current-table fallbacks, verify `DATA_LINEAGE` and `DATA_QUALITY` exclusively against exact run-bound frame evidence and exact DQ certification IDs, ensure exception-to-FAIL semantics, and persist bundle and child rows in an atomic transaction.
- [ ] Task 5.2: Update `PromotionEngine` in `trading_stack/promotion.py` to enforce exact bundle/run/frame binding and compute primary Sharpe ratio and Max Drawdown from stitched out-of-sample equity returns (`strategy_equity_curve` with `evidence_level = 'OUT_OF_SAMPLE'`).
- [ ] Task 5.3: Add certification and promotion adversarial tests in `tests/test_certification_coverage.py` and `tests/test_multi_strategy_platform.py`.

## Phase 6: Vectorized Cost Parity & Paper Sizing Enhancements

- [ ] Task 6.1: Update `StrategyPipeline.run(mode='vectorized')` in `trading_stack/pipeline.py` to instantiate `VectorizedBacktester(cost_model=cost_schedule)` with the effective Indian delivery cost schedule.
- [ ] Task 6.2: Update single-asset paper target position sizing in `trading_stack/paper.py` to size against `current_equity = cash + quantity * price` and compute empirical returns volatility for VaR estimates.

## Phase 7: User Story 5 — E-12: Coverage >= 95%, Type Checking & Verification

- [ ] Task 7.1: Update `.github/workflows/ci.yml` critical coverage scope to include all 11 critical platform files (`risk/*.py,trading_stack/paper.py,trading_stack/portfolio.py,trading_stack/portfolio_paper.py,trading_stack/pipeline.py,trading_stack/datasets.py,trading_stack/certification.py,trading_stack/promotion.py,smartapi/websocket_client.py,trading_stack/live_aggregator.py,storage/migrations/*.py`).
- [ ] Task 7.2: Add focused tests in `tests/test_critical_path_coverage.py` and across test files to reach >= 95.0% coverage across all 11 critical files.
- [ ] Task 7.3: Run full verification suite: pytest, ruff, mypy, pyright, compileall, coverage >=80% global, coverage >=95% critical.
