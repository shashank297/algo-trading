ALTER TABLE frozen_meta_policies ADD COLUMN IF NOT EXISTS simple_comparator VARCHAR DEFAULT NULL;
ALTER TABLE frozen_meta_policies ADD COLUMN IF NOT EXISTS comparator_selection_rule VARCHAR DEFAULT 'highest_validation_after_cost_return_then_B2_B3_B4';
ALTER TABLE frozen_meta_policies ADD COLUMN IF NOT EXISTS comparator_selection_evidence_hash VARCHAR DEFAULT '';
ALTER TABLE frozen_meta_policies ADD COLUMN IF NOT EXISTS comparator_validation_cutoff TIMESTAMPTZ DEFAULT NULL;
