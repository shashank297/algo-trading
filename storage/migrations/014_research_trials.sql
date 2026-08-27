CREATE TABLE IF NOT EXISTS experiment_families (
 experiment_family_id VARCHAR PRIMARY KEY, definition_hash VARCHAR NOT NULL, definition_json VARCHAR NOT NULL,
 maximum_trials BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL, started_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS research_trials_log (
 trial_id VARCHAR PRIMARY KEY, experiment_family_id VARCHAR NOT NULL, status VARCHAR NOT NULL,
 trial_json VARCHAR NOT NULL, metrics_json VARCHAR, metrics_hash VARCHAR, error_message VARCHAR,
 invalidation_reason VARCHAR, created_at TIMESTAMPTZ NOT NULL, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
 invalidated_at TIMESTAMPTZ, selected BOOLEAN NOT NULL DEFAULT FALSE, parent_trial_id VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_trials_family_status ON research_trials_log(experiment_family_id, status);
