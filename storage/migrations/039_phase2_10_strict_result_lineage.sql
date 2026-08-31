ALTER TABLE meta_selector_runs ADD COLUMN IF NOT EXISTS costs_json JSON DEFAULT '[]';
ALTER TABLE final_oos_provenance_certificates ADD COLUMN IF NOT EXISTS outcome_series_bindings JSON DEFAULT '[]';
ALTER TABLE final_oos_provenance_certificates ADD COLUMN IF NOT EXISTS execution_bar_ids JSON DEFAULT '[]';
ALTER TABLE final_oos_provenance_certificates ADD COLUMN IF NOT EXISTS scorecard_ids JSON DEFAULT '[]';
ALTER TABLE final_oos_provenance_certificates ADD COLUMN IF NOT EXISTS conditional_evidence_ids JSON DEFAULT '[]';
ALTER TABLE final_oos_provenance_certificates ADD COLUMN IF NOT EXISTS dataset_certification_bindings JSON DEFAULT '[]';
ALTER TABLE final_oos_provenance_certificates ADD COLUMN IF NOT EXISTS knowledge_cutoff TIMESTAMPTZ DEFAULT NULL;
