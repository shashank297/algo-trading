import hashlib
import json
import pytest

from tools.import_nifty200_pit import verify_manifest
from tools.import_nifty200_pit import load_constituents
from tools.nifty200_pit.manifest import write_table


def _interval(**overrides):
    row = {
        "interval_id": "interval-1",
        "index_id": "NIFTY_200",
        "instrument_id": "NSE-ISIN:INE000A01000",
        "symbol_at_entry": "ABC",
        "effective_from": "2020-01-01",
        "effective_until": None,
        "known_from": "2020-01-01",
        "known_at": "2019-12-31T10:00:00+00:00",
        "entry_event_hash": "event-hash",
        "confidence": "CERTIFIED",
        "synthetic": False,
        "reason": "official",
    }
    row.update(overrides)
    return row


def test_importer_refuses_unapproved_manifest(tmp_path):
    artifact = tmp_path / "constituent_intervals.parquet"
    artifact_bytes = b"not a parquet file"
    artifact.write_bytes(artifact_bytes)
    manifest = tmp_path / "evidence_manifest.json"
    manifest.write_text(json.dumps({
        "validation_status": "PASS",
        "campaign_readiness": "PASS",
        "artifact_hashes": {
            "constituent_intervals.parquet": hashlib.sha256(artifact_bytes).hexdigest(),
        },
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="approval"):
        verify_manifest(manifest, artifact)


def test_importer_structure_validation_does_not_require_governance_flags(tmp_path):
    artifact = tmp_path / "constituent_intervals.parquet"
    artifact_bytes = b"structural-artifact"
    artifact.write_bytes(artifact_bytes)
    manifest = tmp_path / "evidence_manifest.json"
    manifest.write_text(json.dumps({
        "validation_status": "BLOCKED",
        "campaign_readiness": "BLOCKED",
        "approved_for_import": False,
        "artifact_hashes": {
            "constituent_intervals.parquet": hashlib.sha256(artifact_bytes).hexdigest(),
        },
    }), encoding="utf-8")

    assert verify_manifest(manifest, artifact, structure_only=True)["approved_for_import"] is False


def test_structure_validation_rejects_sentinel_identity_and_inverted_interval(tmp_path):
    artifact = tmp_path / "constituent_intervals.parquet"
    write_table(artifact, [_interval(instrument_id="None", effective_until="2020-01-01")])
    with pytest.raises(ValueError, match="missing instrument_id"):
        load_constituents(artifact)


def test_structure_validation_rejects_overlapping_intervals(tmp_path):
    artifact = tmp_path / "constituent_intervals.parquet"
    write_table(artifact, [
        _interval(interval_id="one", effective_until="2021-01-01"),
        _interval(interval_id="two", effective_from="2020-06-01", effective_until=None),
    ])
    with pytest.raises(ValueError, match="overlapping intervals"):
        load_constituents(artifact)
