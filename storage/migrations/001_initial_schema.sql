-- Migration 001: Core Platform Schema Baseline
-- Contains standard base schema for Algo Trading Platform

CREATE TABLE IF NOT EXISTS schema_version (
    version VARCHAR NOT NULL PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
