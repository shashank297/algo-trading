-- Migration 002: Dynamic Capital & Raw Stream Persistence

ALTER TABLE strategy_runs ADD COLUMN IF NOT EXISTS starting_capital DOUBLE DEFAULT 100000.0;

CREATE TABLE IF NOT EXISTS market_raw_packets (
    packet_id VARCHAR NOT NULL PRIMARY KEY,
    token VARCHAR,
    exchange VARCHAR,
    packet_data BLOB NOT NULL,
    packet_length INTEGER NOT NULL,
    received_at TIMESTAMPTZ NOT NULL
);
