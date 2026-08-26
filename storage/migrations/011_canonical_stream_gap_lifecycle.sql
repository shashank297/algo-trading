-- Migration 011: canonical, durable stream-gap lifecycle.
ALTER TABLE stream_gaps ADD COLUMN IF NOT EXISTS gap_start TIMESTAMPTZ;
ALTER TABLE stream_gaps ADD COLUMN IF NOT EXISTS gap_end TIMESTAMPTZ;
ALTER TABLE stream_gaps ADD COLUMN IF NOT EXISTS reanchored_at TIMESTAMPTZ;
ALTER TABLE stream_gaps ADD COLUMN IF NOT EXISTS reanchor_evidence_json TEXT;
ALTER TABLE stream_gaps ADD COLUMN IF NOT EXISTS repair_evidence_json TEXT;

-- Legacy records did not retain sequence bounds. Preserve them as audited
-- legacy evidence rather than silently discarding unresolved intervals.
INSERT INTO stream_gaps (
    gap_id, token, symbol, exchange, expected_sequence, received_sequence,
    gap_size, stream_epoch, detected_at, gap_status, repaired_at,
    gap_start, gap_end, repair_evidence_json
)
SELECT
    event.gap_id, event.token, event.symbol, event.exchange,
    0, event.gap_size, event.gap_size, event.epoch, event.start_time,
    event.status, CASE WHEN event.status = 'REPAIRED' THEN event.recorded_at ELSE NULL END,
    event.start_time, event.end_time,
    '{"source":"stream_gap_events","sequence_bounds":"unavailable"}'
FROM stream_gap_events AS event
WHERE NOT EXISTS (SELECT 1 FROM stream_gaps AS gap WHERE gap.gap_id = event.gap_id);
