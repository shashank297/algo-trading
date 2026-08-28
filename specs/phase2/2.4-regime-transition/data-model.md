# Phase 2.4 Data Model

- `operational_regime_states`: one restart-safe market-regime state per market/benchmark/context key.
- `regime_transition_events`: append-only decision ledger linked to the exact raw `regime_id`.
- `operational_risk_states`: one independent risk posture and recovery dwell per key.
- `risk_state_transition_events`: append-only risk-decision ledger with canonical stress evidence/hash.

State revisions provide optimistic conflict detection. Event IDs are deterministic UUIDv5 values bound
to the raw snapshot, transition policy, and decision evidence.
