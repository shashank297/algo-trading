# Phase 2.5 — Causal Asset-State Snapshots

## Objective

Describe each PIT universe member with a deterministic, interpretable, evidence-bound state snapshot
that future phases may consume without selecting or ranking strategies in Phase 2.5.

## Requirements

- Admit only certified canonical stock and benchmark bars known and available by `decision_time`.
- Resolve exact PIT membership with effective-time and knowledge-time constraints. INTRADAY daily-style
  features use completed D-1 bars only.
- Require 121 causal stock and benchmark sessions for eligibility. Preserve every unavailable optional
  value as `None`; never fabricate sector, market-cap, earnings, or neutral numeric evidence.
- Calculate momentum, trend, relative strength, volatility, ATR, beta, liquidity, volume, gap, and
  mean-reversion evidence using the versioned `AssetStatePolicy`.
- Classify in fixed order as `LOW_LIQUIDITY`, `HIGH_BETA_TRENDING`, `LOW_VOL_TRENDING`,
  `HIGH_VOL_MEAN_REVERTING`, `LIQUID_LARGE_CAP`, or `MIXED_UNCLASSIFIED`.
- Return exactly `ELIGIBLE` or `INELIGIBLE` with ordered deterministic reasons. Missing/invalid critical
  evidence and explicit data-integrity failure fail closed.
- Bind every snapshot to canonical evidence JSON, SHA-256 evidence and policy hashes, model/policy
  versions, decision context, and a deterministic SHA-256 identity.
- Persist snapshots immutably: identical replay is idempotent and a conflicting payload for an existing
  identity fails atomically.

## Non-goals

No strategy selection or ranking, universe-wide batch runner, metadata ingestion, opaque ML clustering,
Phase 2.6 behavior, live routing, or changes to Phase 2.1–2.4 admission and execution invariants.

