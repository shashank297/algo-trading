import json
from datetime import datetime, timezone
from types import SimpleNamespace

from tools.nifty200_pit.manifest import _git_identity, read_table, write_artifacts
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
    assert manifest["approved_for_import"] is False
    assert "event_observations.parquet" in manifest["artifact_hashes"]
    assert "raw_event_observations.parquet" in manifest["artifact_hashes"]
    assert "observation_lineage.parquet" in manifest["artifact_hashes"]
    assert read_table(tmp_path / "artifacts" / "event_observations.parquet").shape[0] == 0


def test_manifest_records_uncommitted_code_identity(monkeypatch, tmp_path):
    import tools.nifty200_pit.manifest as manifest_module

    def fake_run(args, **kwargs):
        command = tuple(args)
        if command == ("git", "rev-parse", "HEAD"):
            return SimpleNamespace(stdout="abc123\n")
        if command == ("git", "status", "--porcelain", "--untracked-files=all"):
            return SimpleNamespace(stdout=" M tools/nifty200_pit/manifest.py\n?? tests/new_test.py\n")
        if command == ("git", "diff", "--binary", "HEAD", "--"):
            return SimpleNamespace(stdout="diff --git a/manifest.py b/manifest.py\n")
        if command == ("git", "ls-files", "--others", "--exclude-standard"):
            return SimpleNamespace(stdout="tests/new_test.py\n")
        raise AssertionError(command)

    monkeypatch.setattr(manifest_module.subprocess, "run", fake_run)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "new_test.py").write_text("assert True\n", encoding="utf-8")

    identity = _git_identity(tmp_path)

    assert identity["head_sha"] == "abc123"
    assert identity["dirty"] is True
    assert identity["execution_id"].startswith("UNCOMMITTED:")
    assert identity["execution_id"] != "abc123"
