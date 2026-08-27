-- Migration 016: Certified Multi-Timeframe Data — Derived Datasets & Cross-Provider Reconciliations
-- Phase 2.2: Creates lineage registry for derived (resampled) datasets and cross-provider verification records.

CREATE TABLE IF NOT EXISTS derived_datasets (
    derived_dataset_id     VARCHAR NOT NULL PRIMARY KEY,
    source_dataset_ids     VARCHAR NOT NULL,          -- JSON array of canonical source dataset_ids
    source_content_hashes  VARCHAR NOT NULL,          -- JSON array of source content hashes
    symbol                 VARCHAR NOT NULL,
    exchange               VARCHAR NOT NULL,
    timeframe              VARCHAR NOT NULL,           -- '5m', '15m', '30m', '60m'
    adjustment_basis       VARCHAR NOT NULL,           -- PriceAdjustment value e.g. 'SPLIT_ADJUSTED'
    resampler_version      VARCHAR NOT NULL,           -- e.g. 'session-resampler-v1'
    calendar_version       VARCHAR NOT NULL,           -- e.g. 'builtin-v1'
    start_ts               TIMESTAMPTZ NOT NULL,
    end_ts                 TIMESTAMPTZ NOT NULL,
    row_count              INTEGER NOT NULL,
    content_hash           VARCHAR NOT NULL,           -- SHA256 of derived bar content
    dq_status              VARCHAR NOT NULL DEFAULT 'PENDING',  -- PENDING | CERTIFIED | DQ_FAILED
    dq_report_json         VARCHAR DEFAULT '{}',
    created_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_derived_symbol_tf ON derived_datasets(symbol, timeframe);
CREATE INDEX IF NOT EXISTS idx_derived_content_hash ON derived_datasets(content_hash);

CREATE TABLE IF NOT EXISTS cross_provider_reconciliations (
    reconciliation_id      VARCHAR NOT NULL PRIMARY KEY,
    symbol                 VARCHAR NOT NULL,
    exchange               VARCHAR NOT NULL,
    timeframe              VARCHAR NOT NULL,
    primary_provider       VARCHAR NOT NULL,
    secondary_provider     VARCHAR NOT NULL,
    comparison_version     VARCHAR NOT NULL,           -- e.g. 'cross-provider-v1'
    comparison_date        DATE NOT NULL,
    primary_dataset_id     VARCHAR NOT NULL,
    secondary_dataset_id   VARCHAR,                    -- NULL when secondary entirely unavailable
    total_bars_primary     INTEGER NOT NULL,
    total_bars_secondary   INTEGER,
    bars_match             INTEGER NOT NULL DEFAULT 0,
    bars_tolerance_match   INTEGER NOT NULL DEFAULT 0,
    bars_disagreement      INTEGER NOT NULL DEFAULT 0,
    bars_unavailable       INTEGER NOT NULL DEFAULT 0,
    tolerance_config_json  VARCHAR NOT NULL DEFAULT '{}',
    bar_outcomes_json      VARCHAR NOT NULL DEFAULT '[]',  -- JSON array of per-bar comparison results
    overall_status         VARCHAR NOT NULL,           -- MATCH | PARTIAL_MATCH | DISAGREEMENT | UNAVAILABLE
    created_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_symbol ON cross_provider_reconciliations(symbol, timeframe, comparison_date);
