import json
import csv
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


def test_manifest_historical_count_and_qa_gates_remain_separate(tmp_path):
    report = ValidationReport(EvidenceStatus.PASS, [], {
        "daily_member_counts": {"2016-04-01": 201},
        "daily_expected_member_counts": {"2016-04-01": 201},
    }, "now")
    _, manifest = write_artifacts(tmp_path, source_records=[], observations=[], events=[], aliases=[],
                                  intervals=[], monthly_snapshots=[], validation_report=report)
    with (tmp_path / "coverage_report.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["required_member_count"] == "201"
    assert rows[0]["status"] == "PASS"
    assert manifest["automated_validation"] == "AUTOMATED_VALIDATION_PASS"
    assert manifest["campaign_readiness"] == "BLOCKED"
    assert manifest["independent_qa"] == "NOT_ASSERTED"
    assert manifest["approved_for_import"] is False
