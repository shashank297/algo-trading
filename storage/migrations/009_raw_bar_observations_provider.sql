-- Migration 009: Add provider_name to raw_bar_observations
ALTER TABLE raw_bar_observations ADD COLUMN IF NOT EXISTS provider_name VARCHAR;
