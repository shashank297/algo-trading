-- Phase 2.4: restart-safe operational regime hysteresis and independent risk state.

CREATE TABLE IF NOT EXISTS operational_regime_states (
    market VARCHAR NOT NULL,
    benchmark VARCHAR NOT NULL,
    context_type VARCHAR NOT NULL,
    operational_regime VARCHAR,
    pending_candidate_regime VARCHAR,
    candidate_started_at TIMESTAMPTZ,
    candidate_observations INTEGER NOT NULL DEFAULT 0,
    candidate_confidence DOUBLE,
    last_raw_regime_id VARCHAR,
    last_decision_time TIMESTAMPTZ,
    policy_version VARCHAR NOT NULL,
    policy_hash VARCHAR NOT NULL,
    revision BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (market, benchmark, context_type)
);

CREATE TABLE IF NOT EXISTS regime_transition_events (
    transition_id VARCHAR PRIMARY KEY,
    market VARCHAR NOT NULL,
    benchmark VARCHAR NOT NULL,
    context_type VARCHAR NOT NULL,
    decision_time TIMESTAMPTZ NOT NULL,
    raw_regime_id VARCHAR NOT NULL REFERENCES market_regime_snapshots(regime_id),
    previous_operational_regime VARCHAR,
    raw_candidate_regime VARCHAR NOT NULL,
    candidate_started_at TIMESTAMPTZ,
    candidate_observations INTEGER NOT NULL,
    candidate_confidence DOUBLE NOT NULL,
    decision VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    operational_regime_after VARCHAR,
    policy_version VARCHAR NOT NULL,
    policy_hash VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS operational_risk_states (
    market VARCHAR NOT NULL,
    benchmark VARCHAR NOT NULL,
    context_type VARCHAR NOT NULL,
    risk_state VARCHAR NOT NULL,
    release_candidate_state VARCHAR,
    release_started_at TIMESTAMPTZ,
    release_observations INTEGER NOT NULL DEFAULT 0,
    last_stress_evidence_hash VARCHAR,
    last_decision_time TIMESTAMPTZ,
    policy_version VARCHAR NOT NULL,
    policy_hash VARCHAR NOT NULL,
    revision BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (market, benchmark, context_type)
);

CREATE TABLE IF NOT EXISTS risk_state_transition_events (
    risk_transition_id VARCHAR PRIMARY KEY,
    market VARCHAR NOT NULL,
    benchmark VARCHAR NOT NULL,
    context_type VARCHAR NOT NULL,
    decision_time TIMESTAMPTZ NOT NULL,
    raw_regime_id VARCHAR NOT NULL REFERENCES market_regime_snapshots(regime_id),
    previous_risk_state VARCHAR NOT NULL,
    stress_evidence_json JSON,
    stress_evidence_hash VARCHAR,
    decision VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    release_candidate_state VARCHAR,
    release_observations INTEGER NOT NULL,
    risk_state_after VARCHAR NOT NULL,
    policy_version VARCHAR NOT NULL,
    policy_hash VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_regime_transition_lookup
    ON regime_transition_events(market, benchmark, context_type, decision_time);
CREATE INDEX IF NOT EXISTS idx_regime_transition_raw
    ON regime_transition_events(raw_regime_id);
CREATE INDEX IF NOT EXISTS idx_risk_transition_lookup
    ON risk_state_transition_events(market, benchmark, context_type, decision_time);
