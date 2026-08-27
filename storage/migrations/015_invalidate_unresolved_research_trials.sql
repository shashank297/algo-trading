-- A governed trial with unresolved lineage was admitted by an earlier Phase 2.1
-- implementation. Preserve its forensic record, but remove its success status.
UPDATE research_trials_log
SET status = 'INVALIDATED',
    selected = FALSE,
    invalidation_reason = COALESCE(
        invalidation_reason,
        'UNRESOLVED_LINEAGE_HISTORICAL_REMEDIATION'
    ),
    invalidated_at = COALESCE(invalidated_at, CURRENT_TIMESTAMP)
WHERE status = 'SUCCEEDED'
  AND json_extract_string(trial_json, '$.data_hash') LIKE 'unresolved:%';
