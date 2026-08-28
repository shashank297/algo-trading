-- Phase 2.5: immutable causal per-asset state snapshots.

CREATE TABLE IF NOT EXISTS asset_state_snapshots (
    asset_state_id VARCHAR PRIMARY KEY,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    context_type VARCHAR NOT NULL,
    as_of DATE NOT NULL,
    decision_time TIMESTAMPTZ NOT NULL,
    trend_score DOUBLE,
    momentum_score DOUBLE,
    volatility_score DOUBLE,
    liquidity_score DOUBLE,
    gap_risk_score DOUBLE,
    mean_reversion_score DOUBLE,
    relative_strength_score DOUBLE,
    beta DOUBLE,
    atr DOUBLE,
    normalized_atr DOUBLE,
    sector VARCHAR,
    market_cap_bucket VARCHAR,
    earnings_proximity INTEGER,
    behavior_cluster VARCHAR NOT NULL,
    cluster_confidence DOUBLE NOT NULL,
    eligibility VARCHAR NOT NULL,
    eligibility_reasons_json JSON NOT NULL,
    features_json JSON NOT NULL,
    input_evidence_manifest_json JSON NOT NULL,
    input_evidence_hash VARCHAR NOT NULL,
    input_hashes_json JSON NOT NULL,
    model_version VARCHAR NOT NULL,
    policy_version VARCHAR NOT NULL,
    policy_hash VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_asset_state_lookup
    ON asset_state_snapshots(symbol, exchange, context_type, decision_time);
CREATE INDEX IF NOT EXISTS idx_asset_state_cluster
    ON asset_state_snapshots(behavior_cluster, decision_time);
CREATE INDEX IF NOT EXISTS idx_asset_state_eligibility
    ON asset_state_snapshots(eligibility, decision_time);
CREATE INDEX IF NOT EXISTS idx_asset_state_evidence
    ON asset_state_snapshots(input_evidence_hash);

