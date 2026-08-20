-- Migration 003: Certifications, research frame validation, and stream gap recovery
-- Atomic certification and provenance schema

CREATE TABLE IF NOT EXISTS data_quality_certifications (
    certification_id VARCHAR PRIMARY KEY,
    dataset_id VARCHAR NOT NULL,
    validator_version VARCHAR NOT NULL,
    check_count INTEGER NOT NULL,
    issue_count INTEGER NOT NULL,
    checks_json TEXT NOT NULL,
    status VARCHAR NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE quality_report ADD COLUMN IF NOT EXISTS certification_id VARCHAR;

CREATE TABLE IF NOT EXISTS research_frame_certifications (
    frame_certification_id VARCHAR PRIMARY KEY,
    research_frame_hash VARCHAR NOT NULL,
    contributing_dataset_ids_json TEXT NOT NULL,
    symbol VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    row_count INTEGER NOT NULL,
    basis VARCHAR NOT NULL,
    validator_version VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    verified_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS run_certifications (
    certification_id VARCHAR PRIMARY KEY,
    bundle_id VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL,
    category VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    evidence_json TEXT NOT NULL,
    certified_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS stream_gap_events (
    gap_id VARCHAR PRIMARY KEY,
    exchange VARCHAR NOT NULL,
    token VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    gap_size INTEGER NOT NULL,
    epoch INTEGER NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'UNREPAIRED',
    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS realtime_bars (
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DOUBLE NOT NULL,
    high DOUBLE NOT NULL,
    low DOUBLE NOT NULL,
    close DOUBLE NOT NULL,
    volume DOUBLE NOT NULL,
    is_authoritative BOOLEAN DEFAULT TRUE,
    quality_status VARCHAR DEFAULT 'TRUSTED',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timeframe, timestamp)
);

CREATE TABLE IF NOT EXISTS market_realtime_bars (
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DOUBLE NOT NULL,
    high DOUBLE NOT NULL,
    low DOUBLE NOT NULL,
    close DOUBLE NOT NULL,
    volume DOUBLE NOT NULL,
    is_authoritative BOOLEAN DEFAULT TRUE,
    quality_status VARCHAR DEFAULT 'TRUSTED',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, timeframe, timestamp)
);
