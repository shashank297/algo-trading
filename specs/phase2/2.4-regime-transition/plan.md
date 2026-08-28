# Phase 2.4 Implementation Plan

1. Add typed policies, operational/risk states, evidence, events, and a pure deterministic reducer in
   `trading_stack/regime_transition.py`.
2. Add migration 020 with append-only transition events and restart-safe current-state tables.
3. Make raw snapshot persistence immutable and add one transactional persistence boundary for raw,
   regime event, risk event, and both state updates with revision checks.
4. Integrate the reducer into the existing `market-regime` command using context-specific configuration
   and causal stress evidence already admitted by Phase 2.3.
5. Certify hysteresis, stress escalation/release, replay, restart, causality, atomicity, and context isolation.
