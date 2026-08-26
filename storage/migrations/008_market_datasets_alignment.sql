-- Migration 008: Align market_datasets and raw_bar_observations schema
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS parent_dataset_id VARCHAR;
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS dataset_stage VARCHAR DEFAULT 'RAW';
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS symbol VARCHAR;
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS canonical_symbol VARCHAR;
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS provider_token VARCHAR;
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS declared_adjustment VARCHAR;
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS lifecycle_status VARCHAR DEFAULT 'RAW_RECORDED';
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS hash_algorithm VARCHAR DEFAULT 'SHA256';
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS hash_version VARCHAR DEFAULT 'raw-provider-v1';
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS row_count INTEGER DEFAULT 0;
ALTER TABLE market_datasets ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;

CREATE TABLE IF NOT EXISTS raw_bar_observations (
    raw_dataset_id VARCHAR NOT NULL,
    source_row_number BIGINT NOT NULL,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    provider_name VARCHAR NOT NULL,
    timestamp_raw VARCHAR,
    open_raw VARCHAR,
    high_raw VARCHAR,
    low_raw VARCHAR,
    close_raw VARCHAR,
    volume_raw VARCHAR,
    raw_row_json VARCHAR NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (raw_dataset_id, source_row_number)
);

ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS raw_dataset_id VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS dataset_id VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS source_row_number BIGINT DEFAULT 0;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS timestamp_raw VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS open_raw VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS high_raw VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS low_raw VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS close_raw VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS volume_raw VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS raw_row_json VARCHAR;
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS retrieved_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;
