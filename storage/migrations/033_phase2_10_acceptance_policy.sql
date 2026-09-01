ALTER TABLE frozen_meta_policies ADD COLUMN IF NOT EXISTS acceptance_policy_version VARCHAR DEFAULT 'phase2-10-acceptance-v1';
ALTER TABLE frozen_meta_policies ADD COLUMN IF NOT EXISTS acceptance_policy_hash VARCHAR DEFAULT '';
ALTER TABLE phase2_10_empirical_acceptance ADD COLUMN IF NOT EXISTS acceptance_policy_version VARCHAR DEFAULT 'phase2-10-acceptance-v1';
ALTER TABLE phase2_10_empirical_acceptance ADD COLUMN IF NOT EXISTS acceptance_policy_hash VARCHAR DEFAULT '';
