# FAB-17 Point-in-Time Universe Readiness

Date: 2026-09-06  
Execution mode: paper-only

## Implementation evidence

- `database_schema.sql` defines `index_constituents_pit` with `instrument_id`, `effective_from`, `effective_until`, and `known_from`.
- `data_platform/universe.py` provides interval insertion, overlap rejection, historical lookup, and precise `known_at` evidence storage.
- `trading_stack/datasets.py` fails closed on missing PIT history or incomplete knowledge fields and computes a deterministic PIT evidence hash.
- `run_pipeline.py` requires and validates a coverage manifest, source certification, coverage periods, membership changes, delistings, and the PIT evidence hash before readiness.
- The causal lookup predicate now enforces `known_at <= as_of_knowledge` even when `known_from` is an earlier date.

## Focused verification

```text
pytest tests/test_universe_pit.py tests/test_campaign1_governance.py -q
26 passed in 9.37s

pytest tests/test_run_pipeline.py tests/test_causality_and_invariants.py::test_p0_4_pit_coverage_fail_closed -q
14 passed in 3.23s
```

The PIT tests cover effective interval look-ahead, former constituents, delisting boundaries, empty PIT fail-closed behavior, canonical identity across symbol history, overlap rejection, and precise announcement-time causality.

## Blocker and handoff

The authoritative local DuckDB could not be read for a live coverage count because DuckDB failed while replaying `market_data.duckdb.wal` (`GetDefaultDatabase ... no default database set`). No repair, deletion, checkpoint, or write was attempted. Therefore current on-disk PIT coverage and the production manifest cannot be independently certified in this run.

Unblock owner: Data/Recovery owner.  
Unblock action: recover or replace the WAL/database with a readable immutable copy, then generate and attach the manifest containing source certification, coverage dates, membership periods, delisting events, and matching `pit_evidence_hash`.  
Reviewer: Independent QA / Risk Lead.

Rollback: code change is limited to the knowledge-time SQL predicate and regression tests; reverting that predicate restores prior behavior. No database or live-order state was changed.
