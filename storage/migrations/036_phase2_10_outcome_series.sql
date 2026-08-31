CREATE TABLE IF NOT EXISTS phase2_10_outcome_series (
    series_id VARCHAR NOT NULL,
    series_type VARCHAR NOT NULL,
    strategy_name VARCHAR,
    symbol VARCHAR NOT NULL,
    universe_snapshot_id VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    observation_time TIMESTAMPTZ NOT NULL,
    holding_end TIMESTAMPTZ NOT NULL,
    value DOUBLE NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    content_hash VARCHAR NOT NULL,
    PRIMARY KEY (series_id, observation_time)
);
