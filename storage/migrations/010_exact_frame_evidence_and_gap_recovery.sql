-- Migration 010: Exact Frame Evidence and Stream Gap Recovery Alignment

ALTER TABLE research_frame_certifications ADD COLUMN IF NOT EXISTS dataset_evidence_json VARCHAR DEFAULT '{}';
ALTER TABLE research_frame_certifications ADD COLUMN IF NOT EXISTS dq_certification_ids_json VARCHAR DEFAULT '[]';
ALTER TABLE research_frame_certifications ADD COLUMN IF NOT EXISTS pit_evidence_hash VARCHAR;

CREATE TABLE IF NOT EXISTS stream_gaps (
    gap_id VARCHAR NOT NULL PRIMARY KEY,
    token VARCHAR NOT NULL,
    symbol VARCHAR,
    exchange VARCHAR NOT NULL,
    expected_sequence BIGINT NOT NULL,
    received_sequence BIGINT NOT NULL,
    gap_size BIGINT NOT NULL,
    stream_epoch BIGINT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    gap_status VARCHAR NOT NULL DEFAULT 'UNREPAIRED',
    repaired_at TIMESTAMPTZ
);

ALTER TABLE stream_gaps ADD COLUMN IF NOT EXISTS symbol VARCHAR;
ALTER TABLE stream_gaps ADD COLUMN IF NOT EXISTS gap_size BIGINT DEFAULT 1;
ALTER TABLE stream_gaps ADD COLUMN IF NOT EXISTS stream_epoch BIGINT DEFAULT 1;
ALTER TABLE stream_gaps ADD COLUMN IF NOT EXISTS gap_status VARCHAR DEFAULT 'UNREPAIRED';
ALTER TABLE stream_gaps ADD COLUMN IF NOT EXISTS repaired_at TIMESTAMPTZ;
