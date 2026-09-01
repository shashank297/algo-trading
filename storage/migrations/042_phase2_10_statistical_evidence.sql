CREATE TABLE IF NOT EXISTS phase2_10_statistical_evidence (
    statistical_evidence_id VARCHAR PRIMARY KEY,
    meta_run_id VARCHAR NOT NULL,
    frozen_policy_id VARCHAR DEFAULT NULL,
    selected_trial_id VARCHAR DEFAULT NULL,
    experiment_family_id VARCHAR NOT NULL,
    source_execution_hash VARCHAR NOT NULL,
    source_equity_hash VARCHAR NOT NULL,
    returns_hash VARCHAR NOT NULL,
    meta_policy_hash VARCHAR NOT NULL,
    acceptance_policy_hash VARCHAR NOT NULL,
    evidence_json JSON NOT NULL,
    observation_count BIGINT NOT NULL,
    independent_trade_count BIGINT NOT NULL,
    materialized_at TIMESTAMPTZ NOT NULL,
    evidence_hash VARCHAR NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_phase2_10_statistical_evidence_run
ON phase2_10_statistical_evidence(meta_run_id);

ALTER TABLE final_oos_provenance_certificates ADD COLUMN IF NOT EXISTS statistical_evidence_id VARCHAR DEFAULT '';
ALTER TABLE final_oos_provenance_certificates ADD COLUMN IF NOT EXISTS statistical_evidence_hash VARCHAR DEFAULT '';
