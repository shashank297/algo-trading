-- Historical dated aliases tied to durable instrument identities.
-- Prevents unrestricted global symbol mapping and bounds alias matching to evidence-backed periods.
CREATE TABLE IF NOT EXISTS instrument_alias_history (
    alias_id VARCHAR NOT NULL PRIMARY KEY,
    instrument_id VARCHAR NOT NULL,
    alias_symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL DEFAULT 'NSE',
    valid_from DATE,
    valid_until DATE,
    source_url VARCHAR,
    source_sha256 VARCHAR,
    confidence VARCHAR NOT NULL DEFAULT 'MANUAL_REVIEW',
    resolution_status VARCHAR NOT NULL DEFAULT 'UNRESOLVED',
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CHECK (valid_until IS NULL OR (valid_from IS NOT NULL AND valid_from < valid_until))
);

-- Ensure external_approval_evidence has cryptographic signature columns
ALTER TABLE external_approval_evidence ADD COLUMN IF NOT EXISTS issuer_key_id VARCHAR;
ALTER TABLE external_approval_evidence ADD COLUMN IF NOT EXISTS signature VARCHAR;
