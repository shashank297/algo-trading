import json
from datetime import datetime, timezone

from tools.nifty200_pit.manifest import read_table, write_artifacts
from tools.nifty200_pit.models import EvidenceStatus, ValidationReport


def test_manifest_binds_parquet_artifacts_and_keeps_qa_unasserted(tmp_path):
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"official")
    from tools.nifty200_pit.source_catalogue import SourceCatalogue

    source = SourceCatalogue(tmp_path / "sources").add_file(source_path, source_url="https://nse.example/source.pdf")
    report = ValidationReport(EvidenceStatus.BLOCKED, ["no evidence"], {"high_critical_conflicts": 0}, datetime.now(timezone.utc).isoformat())
    manifest_path, _ = write_artifacts(tmp_path / "artifacts", source_records=[source], observations=[], events=[], aliases=[], intervals=[], monthly_snapshots=[], validation_report=report)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["validation_status"] == "BLOCKED"
    assert manifest["independent_qa"] == "NOT_ASSERTED"
    assert "event_observations.parquet" in manifest["artifact_hashes"]
    assert read_table(tmp_path / "artifacts" / "event_observations.parquet").shape[0] == 0
