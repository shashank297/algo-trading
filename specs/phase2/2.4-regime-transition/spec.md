# Phase 2.4 — Operational Regime Transition

## Objective

Prevent raw Phase 2.3 classifications from thrashing operational behavior while preserving complete,
immutable raw history and causal reproducibility.

## Requirements

- Maintain a two-layer design: immutable raw snapshots and a separate operational regime state.
- Confirm changes with versioned minimum confidence, confidence buffer, consecutive dwell observations,
  and a maximum pending duration. Bootstrap the first eligible classification immediately.
- Keep `INSUFFICIENT_CONTEXT` non-operational; hold or remain uninitialized and clear pending dwell.
- Persist independent state for every market/benchmark/EOD-or-INTRADAY key and restore pending counters after restart.
- Model `NORMAL`, `CAUTION`, and `STRESS` independently. Use only explicit policy thresholds, escalate
  immediately, and require recovery dwell for release.
- Reject naive, future, or out-of-order evidence. Make exact replay idempotent and deterministic.
- Persist every non-replay regime and risk decision as an immutable event in the same transaction as
  the raw snapshot and current states.

## Non-goals

No Phase 2.3 scoring changes, strategy selection, asset-state classification, live routing, or capital allocation.
