-- Migration 017: Market Regime Snapshots Table
-- Description: Immutable point-in-time storage for market context features, normalized component scores, and raw market regime classifications.

CREATE TABLE IF NOT EXISTS market_regime_snapshots (
    regime_id VARCHAR PRIMARY KEY,
    market VARCHAR NOT NULL,
    benchmark VARCHAR NOT NULL,
    context_type VARCHAR NOT NULL,
    as_of DATE NOT NULL,
    decision_time TIMESTAMP WITH TIME ZONE NOT NULL,
    raw_regime VARCHAR NOT NULL,
    confidence DOUBLE NOT NULL,
    trend_score DOUBLE NOT NULL,
    volatility_score DOUBLE NOT NULL,
    breadth_score DOUBLE NOT NULL,
    dispersion_score DOUBLE NOT NULL,
    liquidity_score DOUBLE NOT NULL,
    stress_score DOUBLE NOT NULL,
    input_evidence_json JSON NOT NULL,
    input_evidence_hash VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    policy_version VARCHAR NOT NULL,
    policy_hash VARCHAR NOT NULL,
    calendar_version VARCHAR NOT NULL,
    missing_evidence_json JSON NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_regime_lookup ON market_regime_snapshots(market, context_type, as_of, decision_time);
CREATE INDEX IF NOT EXISTS idx_regime_evidence ON market_regime_snapshots(input_evidence_hash);
