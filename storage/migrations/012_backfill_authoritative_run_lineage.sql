-- Migration 012: one-time migration of legacy display metadata into authority column.
UPDATE strategy_runs
SET frame_certification_id = json_extract_string(try_cast(notes AS JSON), '$.frame_certification_id')
WHERE frame_certification_id IS NULL
  AND json_extract_string(try_cast(notes AS JSON), '$.frame_certification_id') IS NOT NULL;
