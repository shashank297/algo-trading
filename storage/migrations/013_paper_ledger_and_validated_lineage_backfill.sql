-- Migration 013: append-only paper intent authority and validated legacy lineage correction.
CREATE TABLE IF NOT EXISTS paper_position_intents (
    intent_id VARCHAR NOT NULL PRIMARY KEY,
    session_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    desired_quantity DOUBLE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (session_id, symbol, as_of)
);

CREATE TABLE IF NOT EXISTS lineage_backfill_rejections (
    run_id VARCHAR NOT NULL PRIMARY KEY,
    legacy_frame_certification_id VARCHAR,
    rejection_reason VARCHAR NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL
);

-- Correct only runs whose direct value was populated by migration 012 but cannot
-- be proven against the referenced frame. The original notes value remains audit
-- metadata; runtime certification never reads it.
INSERT INTO lineage_backfill_rejections (run_id, legacy_frame_certification_id, rejection_reason, recorded_at)
SELECT sr.run_id, sr.frame_certification_id,
       CASE
           WHEN rfc.frame_certification_id IS NULL THEN 'FRAME_NOT_FOUND'
           WHEN rfc.symbol <> sr.symbol THEN 'SYMBOL_MISMATCH'
           WHEN rfc.timeframe <> sr.timeframe THEN 'TIMEFRAME_MISMATCH'
           WHEN sr.data_hash IS NULL OR sr.data_hash = '' THEN 'RUN_HASH_MISSING'
           WHEN rfc.research_frame_hash <> sr.data_hash THEN 'FRAME_HASH_MISMATCH'
           ELSE 'UNVERIFIABLE_LEGACY_LINEAGE'
       END,
       CURRENT_TIMESTAMP
FROM strategy_runs sr
LEFT JOIN research_frame_certifications rfc
  ON rfc.frame_certification_id = sr.frame_certification_id
WHERE sr.frame_certification_id IS NOT NULL
  AND NOT (
      rfc.frame_certification_id IS NOT NULL
      AND rfc.symbol = sr.symbol
      AND rfc.timeframe = sr.timeframe
      AND sr.data_hash IS NOT NULL
      AND sr.data_hash <> ''
      AND rfc.research_frame_hash = sr.data_hash
  )
ON CONFLICT (run_id) DO NOTHING;

UPDATE strategy_runs
SET frame_certification_id = NULL
WHERE run_id IN (SELECT run_id FROM lineage_backfill_rejections);
