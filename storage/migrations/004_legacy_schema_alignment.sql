-- Migration 004: Legacy schema alignment and indexes
-- Ensures all primary keys, indexes, and metadata columns are aligned across legacy schemas

CREATE TABLE IF NOT EXISTS system_metadata (
    key VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE trade_attribution ADD COLUMN IF NOT EXISTS quantity DOUBLE;
ALTER TABLE trade_attribution ADD COLUMN IF NOT EXISTS price DOUBLE;
ALTER TABLE trade_attribution ADD COLUMN IF NOT EXISTS gross_pnl DOUBLE;
ALTER TABLE trade_attribution ADD COLUMN IF NOT EXISTS net_pnl DOUBLE;
ALTER TABLE trade_attribution ADD COLUMN IF NOT EXISTS holding_period_days DOUBLE;
ALTER TABLE trade_attribution ADD COLUMN IF NOT EXISTS exit_reason VARCHAR;
ALTER TABLE trade_attribution ADD COLUMN IF NOT EXISTS exit_classification VARCHAR;
ALTER TABLE trade_attribution ADD COLUMN IF NOT EXISTS metadata_json TEXT;

ALTER TABLE strategy_correlations ADD COLUMN IF NOT EXISTS run_id_a VARCHAR;
ALTER TABLE strategy_correlations ADD COLUMN IF NOT EXISTS run_id_b VARCHAR;
ALTER TABLE strategy_correlations ADD COLUMN IF NOT EXISTS symbol_a VARCHAR;
ALTER TABLE strategy_correlations ADD COLUMN IF NOT EXISTS symbol_b VARCHAR;

ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS action_id VARCHAR;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS record_date DATE;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS announcement_date DATE;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS payment_date DATE;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS bonus_new_shares DOUBLE;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS bonus_existing_shares DOUBLE;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS old_face_value DOUBLE;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS new_face_value DOUBLE;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS currency VARCHAR DEFAULT 'INR';
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS purpose VARCHAR;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS source_event_id VARCHAR;
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'VERIFIED';

CREATE TABLE IF NOT EXISTS corporate_actions_aligned (
    action_id VARCHAR PRIMARY KEY,
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL DEFAULT 'NSE',
    action_type VARCHAR NOT NULL,
    ex_date DATE NOT NULL,
    record_date DATE,
    announcement_date DATE,
    payment_date DATE,
    share_multiplier DOUBLE NOT NULL DEFAULT 1.0,
    bonus_new_shares DOUBLE,
    bonus_existing_shares DOUBLE,
    old_face_value DOUBLE,
    new_face_value DOUBLE,
    dividend_amount DOUBLE DEFAULT 0.0,
    currency VARCHAR NOT NULL DEFAULT 'INR',
    purpose VARCHAR,
    source VARCHAR NOT NULL,
    source_event_id VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'VERIFIED',
    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

INSERT OR REPLACE INTO corporate_actions_aligned
SELECT 
    COALESCE(action_id, md5(concat_ws(':', symbol, COALESCE(exchange, 'NSE'), action_type, CAST(ex_date AS VARCHAR), COALESCE(source, 'UNKNOWN'), COALESCE(source_event_id, '')))),
    symbol,
    COALESCE(exchange, 'NSE'),
    action_type,
    ex_date,
    record_date,
    announcement_date,
    payment_date,
    COALESCE(share_multiplier, 1.0),
    bonus_new_shares,
    bonus_existing_shares,
    old_face_value,
    new_face_value,
    COALESCE(dividend_amount, 0.0),
    COALESCE(currency, 'INR'),
    purpose,
    source,
    source_event_id,
    COALESCE(status, 'VERIFIED'),
    recorded_at
FROM corporate_actions;

DROP TABLE corporate_actions;
ALTER TABLE corporate_actions_aligned RENAME TO corporate_actions;
