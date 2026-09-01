CREATE TABLE IF NOT EXISTS frozen_meta_policies (
    frozen_policy_id VARCHAR PRIMARY KEY,
    selector_policy_version VARCHAR NOT NULL,
    selector_policy_hash VARCHAR NOT NULL,
    scorecard_policy_hash VARCHAR NOT NULL,
    meta_policy_version VARCHAR NOT NULL,
    meta_policy_hash VARCHAR NOT NULL,
    candidate_trial_ids JSON NOT NULL,
    selected_trial_id VARCHAR NOT NULL,
    data_hash VARCHAR NOT NULL,
    universe_lineage JSON NOT NULL,
    cost_model_version VARCHAR NOT NULL,
    cost_model_hash VARCHAR NOT NULL,
    purge_periods INTEGER NOT NULL,
    embargo_periods INTEGER NOT NULL,
    frozen_at TIMESTAMPTZ NOT NULL,
    artifact_hash VARCHAR NOT NULL
);
