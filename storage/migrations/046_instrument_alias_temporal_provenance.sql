-- Preserve the evidence dates and validity basis that bound certified alias use.
ALTER TABLE instrument_alias_history ADD COLUMN IF NOT EXISTS listing_date DATE;
ALTER TABLE instrument_alias_history ADD COLUMN IF NOT EXISTS snapshot_date DATE;
ALTER TABLE instrument_alias_history ADD COLUMN IF NOT EXISTS observed_snapshot_date DATE;
ALTER TABLE instrument_alias_history ADD COLUMN IF NOT EXISTS validity_basis VARCHAR;
ALTER TABLE instrument_alias_history ADD COLUMN IF NOT EXISTS has_explicit_historical_interval BOOLEAN DEFAULT FALSE;
