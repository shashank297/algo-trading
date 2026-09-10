-- NIFTY-200 PIT reconstruction staging. Canonical production imports remain
-- guarded by tools/import_nifty200_pit.py and the PointInTime API.
CREATE TABLE IF NOT EXISTS nifty200_event_observations (
    observation_id VARCHAR PRIMARY KEY,
    index_id VARCHAR NOT NULL,
    instrument_id VARCHAR,
    isin VARCHAR,
    symbol VARCHAR,
    company_name VARCHAR,
    announcement_date DATE,
    known_at TIMESTAMPTZ,
    known_at_basis VARCHAR,
    effective_date DATE,
    action VARCHAR,
    reason VARCHAR,
    source_url VARCHAR NOT NULL,
    archive_url VARCHAR,
    source_sha256 VARCHAR NOT NULL,
    source_page INTEGER,
    source_tier VARCHAR NOT NULL,
    extraction_method VARCHAR NOT NULL,
    extractor_version VARCHAR NOT NULL,
    confidence VARCHAR NOT NULL,
    review_status VARCHAR NOT NULL,
    observation_hash VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS nifty200_pit_canonical (
    interval_id VARCHAR PRIMARY KEY,
    index_id VARCHAR NOT NULL,
    instrument_id VARCHAR NOT NULL,
    symbol_at_entry VARCHAR,
    isin_at_entry VARCHAR,
    effective_from DATE NOT NULL,
    effective_until DATE,
    known_from DATE NOT NULL,
    known_at TIMESTAMPTZ NOT NULL,
    reason VARCHAR,
    entry_event_hash VARCHAR NOT NULL,
    exit_event_hash VARCHAR,
    confidence VARCHAR NOT NULL,
    dataset_version VARCHAR NOT NULL
);
