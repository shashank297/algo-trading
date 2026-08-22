-- Migration 005: immutable run certification bundle and dataset content binding

CREATE TABLE IF NOT EXISTS run_certification_bundles (
    bundle_id VARCHAR PRIMARY KEY,
    run_id VARCHAR NOT NULL,
    run_data_hash VARCHAR NOT NULL,
    frame_certification_id VARCHAR,
    certification_version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE strategy_runs ADD COLUMN IF NOT EXISTS frame_certification_id VARCHAR;
