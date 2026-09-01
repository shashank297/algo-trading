ALTER TABLE final_oos_provenance_certificates ADD COLUMN IF NOT EXISTS acceptance_policy_version VARCHAR DEFAULT 'phase2-10-acceptance-v1';
ALTER TABLE final_oos_provenance_certificates ADD COLUMN IF NOT EXISTS acceptance_policy_hash VARCHAR DEFAULT '';

CREATE TABLE IF NOT EXISTS research_trial_lifecycle_events (
    event_id VARCHAR PRIMARY KEY,
    trial_id VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    event_hash VARCHAR NOT NULL,
    metadata_json JSON NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trial_lifecycle_asof
ON research_trial_lifecycle_events(trial_id, effective_at, recorded_at, event_id);
