-- Phase 2.3 final causal-evidence persistence.  Never alter applied migrations.
ALTER TABLE market_regime_snapshots
    ADD COLUMN IF NOT EXISTS input_evidence_manifest_json JSON;
ALTER TABLE market_regime_snapshots
    ADD COLUMN IF NOT EXISTS component_evidence_json JSON;

DROP INDEX IF EXISTS idx_regime_lookup;
DROP INDEX IF EXISTS idx_regime_evidence;
ALTER TABLE market_regime_snapshots ALTER COLUMN dispersion_score DROP NOT NULL;
ALTER TABLE market_regime_snapshots ALTER COLUMN liquidity_score DROP NOT NULL;
CREATE INDEX IF NOT EXISTS idx_regime_lookup ON market_regime_snapshots(market, context_type, as_of, decision_time);
CREATE INDEX IF NOT EXISTS idx_regime_evidence ON market_regime_snapshots(input_evidence_hash);
