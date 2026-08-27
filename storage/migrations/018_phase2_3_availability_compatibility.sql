-- Keep legacy INSERT ... VALUES callers source-compatible while storing immutable
-- knowledge-time evidence in keyed companion tables.
ALTER TABLE historical_candles DROP COLUMN IF EXISTS available_at;
ALTER TABLE index_constituents_pit DROP COLUMN IF EXISTS known_at;

CREATE TABLE IF NOT EXISTS market_dataset_availability (
    dataset_id VARCHAR NOT NULL PRIMARY KEY,
    available_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS historical_candle_availability (
    dataset_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (dataset_id, symbol, exchange, timeframe, timestamp)
);

CREATE TABLE IF NOT EXISTS index_constituent_knowledge (
    universe_name VARCHAR NOT NULL,
    instrument_id VARCHAR NOT NULL,
    effective_from DATE NOT NULL,
    known_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (universe_name, instrument_id, effective_from)
);
