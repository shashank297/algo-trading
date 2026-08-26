-- Migration 006: immutable exact research-frame evidence.
ALTER TABLE research_frame_certifications ADD COLUMN IF NOT EXISTS dataset_evidence_json TEXT;
ALTER TABLE research_frame_certifications ADD COLUMN IF NOT EXISTS dq_certification_ids_json TEXT;
ALTER TABLE research_frame_certifications ADD COLUMN IF NOT EXISTS pit_evidence_hash VARCHAR;
ALTER TABLE run_certifications ADD COLUMN IF NOT EXISTS evidence_hash VARCHAR;
