ALTER TABLE frozen_meta_policies ADD COLUMN IF NOT EXISTS selector_policy_payload JSON DEFAULT '{}';
ALTER TABLE frozen_meta_policies ADD COLUMN IF NOT EXISTS meta_policy_payload JSON DEFAULT '{}';
ALTER TABLE frozen_meta_policies ADD COLUMN IF NOT EXISTS scorecard_policy_payload JSON DEFAULT '{}';

CREATE TABLE IF NOT EXISTS final_oos_provenance_certificates (
    certificate_id VARCHAR PRIMARY KEY,
    frozen_policy_id VARCHAR NOT NULL,
    frozen_policy_hash VARCHAR NOT NULL,
    selected_trial_id VARCHAR NOT NULL,
    experiment_family_id VARCHAR NOT NULL,
    selector_policy_hash VARCHAR NOT NULL,
    meta_policy_hash VARCHAR NOT NULL,
    scorecard_policy_hash VARCHAR NOT NULL,
    dataset_ids JSON NOT NULL,
    dataset_content_hashes JSON NOT NULL,
    evidence_hashes JSON NOT NULL,
    resolver_hash VARCHAR NOT NULL,
    execution_hash VARCHAR NOT NULL,
    final_oos_start TIMESTAMPTZ NOT NULL,
    final_oos_end TIMESTAMPTZ NOT NULL,
    materialized_at TIMESTAMPTZ NOT NULL,
    cost_model_version VARCHAR NOT NULL,
    cost_model_hash VARCHAR NOT NULL,
    purge_periods INTEGER NOT NULL,
    embargo_periods INTEGER NOT NULL,
    certificate_hash VARCHAR NOT NULL
);
