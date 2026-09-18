import csv
import json

from tools.nifty200_pit.evidence_closure import generate


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def test_evidence_closure_writes_case_files_without_promoting_blockers(tmp_path):
    artifact_root = tmp_path / "artifacts" / "nifty200_pit_v1"
    report_root = tmp_path / "reports"
    ledger_columns = [
        "blocker_id", "blocker_type", "date", "year", "symbol", "company",
        "instrument_id", "isin", "expected_value", "observed_value", "source_tier",
        "source_url", "source_sha256", "severity", "root_cause", "resolution_status",
        "resolution_source", "notes",
    ]
    rows = [
        dict.fromkeys(ledger_columns, "") | {
            "blocker_id": "identity-1", "blocker_type": "MISSING_DURABLE_IDENTITY",
            "date": "2016-04-01", "symbol": "ABC", "company": "ABC Ltd",
        },
        dict.fromkeys(ledger_columns, "") | {
            "blocker_id": "announcement-1", "blocker_type": "MISSING_ANNOUNCEMENT_DATE",
            "date": "2020-06-26", "symbol": "XYZ", "company": "XYZ Ltd",
        },
    ]
    _write_csv(artifact_root / "blocker_ledger.csv", rows)
    _write_csv(
        report_root / "nifty200_pit_monthly_gap_analysis.csv",
        [{"status": "A_NO_SNAPSHOT_EVIDENCE", "source_issue": "A_NO_SNAPSHOT_EVIDENCE"}],
    )
    (artifact_root / "validation_report.json").write_text(
        json.dumps({
            "status": "BLOCKED", "passed": False,
            "metrics": {"source_count": 2, "conflict_count": 1},
        }),
        encoding="utf-8",
    )

    result = generate(tmp_path)

    assert result["identity_cases"] == 1
    assert result["announcement_cases"] == 1
    assert result["validation_status"] == "BLOCKED"
    identity_text = (report_root / "nifty200_pit_identity_blocker_cases.csv").read_text(
        encoding="utf-8"
    )
    assert "MANUAL_REVIEW" in identity_text
    assert ",,ABC,ABC Ltd," in identity_text
    assert (report_root / "nifty200_pit_monthly_checkpoint_governance_decision.md").exists()
    assert "DATA EVIDENCE BLOCKED" in (
        report_root / "nifty200_pit_evidence_closure_current.md"
    ).read_text(encoding="utf-8")
