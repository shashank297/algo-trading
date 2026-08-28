# Operational Regime Transition (Phase 2.4)

Phase 2.4 prevents raw-regime boundary noise from immediately changing the regime used by downstream
operations. It does not alter Phase 2.3 classification or select strategies.

## State model

- Layer A is the immutable `MarketRegimeSnapshot.raw_regime` produced by Phase 2.3.
- Layer B is one operational market regime per `(market, benchmark, context_type)`.
- `INSUFFICIENT_CONTEXT` is never an operational market regime. It holds the current state, or leaves a new state uninitialized.
- EOD and INTRADAY observations have independent pending counters and operational states.
- Risk posture is a separate `NORMAL`, `CAUTION`, or `STRESS` state and never replaces a market regime.

The first eligible raw regime initializes the operational state. Later changes require consecutive
observations with confidence at least `minimum_confidence + transition_buffer`. A changed, missing, or
low-confidence candidate cancels the pending dwell. A pending candidate that exceeds
`maximum_pending_duration` restarts at observation one.

## Emergency risk policy

Stress override is disabled until operators supply explicit versioned thresholds. When enabled, any
configured benchmark-loss, volatility-shock, gap, liquidity-collapse, or data-integrity trigger can
escalate risk immediately. De-escalation requires `stress_release_dwell` consecutive recovery
observations; absence of causal stress evidence never releases an elevated state.

For INTRADAY decisions, immediate loss and gap evidence is calculated from certified completed
current-session intraday bars against the prior completed daily close. Those bars never enter the
Phase 2.3 daily feature series. Ordinary missing history or `INSUFFICIENT_CONTEXT` is not an integrity
failure; only an explicit, completed DQ rejection with no certified fallback can trigger that signal.

## Persistence and replay

Migration 020 adds current operational/risk state tables and separate immutable event tables. Each
state row persists pending candidate/release counters, start time, last raw snapshot, policy identity,
and revision. Raw snapshot, transition events, and both state rows commit atomically. Identical replay
is idempotent; conflicting raw payloads, stale revisions, naive timestamps, future stress evidence, and
out-of-order observations fail closed.

`research.py --command market-regime` prints the raw snapshot plus `operational_regime`, `hysteresis`,
and `stress_state`. Replay requires the same raw snapshot, transition-policy hash, and stress-evidence
hash; a policy change creates a new decision and resets pending dwell safely.
