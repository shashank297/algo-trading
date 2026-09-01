ALTER TABLE meta_selector_runs ADD COLUMN IF NOT EXISTS execution_payload_json JSON DEFAULT '{}';
ALTER TABLE meta_selector_runs ADD COLUMN IF NOT EXISTS pre_verdict_result_hash VARCHAR DEFAULT '';
ALTER TABLE meta_selector_runs ADD COLUMN IF NOT EXISTS pre_verdict_result_payload_json JSON DEFAULT '{}';
