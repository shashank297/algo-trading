ALTER TABLE frozen_meta_policies ADD COLUMN IF NOT EXISTS selection_rule VARCHAR;
ALTER TABLE frozen_meta_policies ADD COLUMN IF NOT EXISTS selection_result VARCHAR;
