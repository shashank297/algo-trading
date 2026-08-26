-- Migration 007: Align quality_report table with dataset_id column
ALTER TABLE quality_report ADD COLUMN IF NOT EXISTS dataset_id VARCHAR;
