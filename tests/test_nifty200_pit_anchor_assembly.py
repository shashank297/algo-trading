"""Assembly must bind derivation to its actual registry, ledger and opening."""

from datetime import datetime
import hashlib
import json

import pytest

from tools.nifty200_pit import anchor_derivation, bounded_producer


@pytest.fixture
def derivation_input(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.csv"
    ledger.write_text("registered ledger")
    members = [{"symbol": "ONE", "instrument_id": "id1", "isin": "isin1"}]
    candidate = {"date": "2016-01-29", "confidence": "UNRESOLVED",
                 "review_status": "MANUAL_REVIEW", "known_at": None, "members": members}
    registry = [{"source_url": "actual", "source_sha256": "a" * 64}]
    def derive(**kwargs):
        assert kwargs["catalogue"] is registry
        return candidate
    monkeypatch.setattr(anchor_derivation, "derive_anchor_candidate", derive)
    payload = {"start_at": "2016-01-29T09:15:00+05:30", "seed": {}, "notices": [],
               "renames": [], "catalogue": [{"source_url": "forged"}],
               "checkpoint": {"local_path": str(ledger),
                              "source_sha256": hashlib.sha256(ledger.read_bytes()).hexdigest()}}
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps(payload))
    return path, payload, candidate, registry, members, ledger


def call(case):
    path, _, _, registry, members, ledger = case
    return bounded_producer._anchor_from_derivation(
        path, catalogue=registry, expected_members=members, ledger_path=ledger,
        opening=datetime.fromisoformat("2016-01-29T09:15:00+05:30"),
    )


def test_assembly_uses_actual_registry_and_retains_unresolved_anchor(derivation_input):
    result = call(derivation_input)
    assert result["confidence"] == "UNRESOLVED"
    assert result["known_at"] is None


@pytest.mark.parametrize("change", ["ledger", "opening", "identity", "admission"])
def test_assembly_rejects_derivation_input_substitution(derivation_input, change):
    path, payload, candidate, _, _, _ = derivation_input
    if change == "ledger":
        payload["checkpoint"]["source_sha256"] = "f" * 64
    elif change == "opening":
        payload["start_at"] = "2016-01-29T09:16:00+05:30"
    elif change == "identity":
        candidate["members"] = [{"symbol": "ONE", "instrument_id": "other", "isin": "isin1"}]
    else:
        candidate["confidence"] = "CERTIFIED"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="anchor_derivation"):
        call(derivation_input)


def test_assembly_admits_anchor_when_admit_flag_is_set(derivation_input):
    path, _, _, registry, members, ledger = derivation_input
    result = bounded_producer._anchor_from_derivation(
        path, catalogue=registry, expected_members=members, ledger_path=ledger,
        opening=datetime.fromisoformat("2016-01-29T09:15:00+05:30"),
        admit=True,
    )
    assert result["confidence"] == "CERTIFIED"
    assert result["review_status"] == "ACCEPTED"
    assert result["known_at"] == "2016-01-29T09:15:00+05:30"
    assert result["causal_availability_status"] == "CERTIFIED"
    assert all(
        m["confidence"] == "CERTIFIED"
        and m["review_status"] == "ACCEPTED"
        and m["has_explicit_historical_interval"] is True
        for m in result["members"]
    )


def test_assembly_cannot_admit_derivation_with_missing_causal_evidence(derivation_input):
    path, _, candidate, registry, members, ledger = derivation_input
    candidate["missing_evidence"] = ["causal_availability_not_established"]

    with pytest.raises(ValueError, match="anchor_derivation_evidence_unresolved"):
        bounded_producer._anchor_from_derivation(
            path, catalogue=registry, expected_members=members, ledger_path=ledger,
            opening=datetime.fromisoformat("2016-01-29T09:15:00+05:30"),
            admit=True,
        )
