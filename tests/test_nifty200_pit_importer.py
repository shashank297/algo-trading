import json
import pytest

from tools.import_nifty200_pit import verify_manifest


def test_importer_refuses_unapproved_manifest(tmp_path):
    artifact = tmp_path / "constituent_intervals.parquet"
    artifact.write_bytes(b"not a parquet file")
    manifest = tmp_path / "evidence_manifest.json"
    manifest.write_text(json.dumps({"validation_status": "PASS", "campaign_readiness": "PASS", "artifact_hashes": {"constituent_intervals.parquet": "x" * 64}}), encoding="utf-8")
    with pytest.raises(ValueError, match="approval"):
        verify_manifest(manifest, artifact)
