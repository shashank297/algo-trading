import pytest

from trading_stack.foundation_certification import (
    build_foundation_certification,
    require_realtime_paper_certification,
    validate_manifest,
)


def _all_pass():
    return {name: {"status": "PASS", "reason": "verified"} for name in (
        "PIT", "LINEAGE", "TRANSACTION_COSTS", "ROBUSTNESS", "KPI",
        "RISK_CONFIGURATION", "INDEPENDENT_QA_RISK",
    )}


def test_missing_gate_is_blocked_and_flags_are_false():
    artifact = build_foundation_certification(
        gates={"PIT": {"status": "BLOCKED", "reason": "external historical membership unavailable"}},
        generated_at="2026-09-06T00:00:00Z",
    )
    assert artifact["final_verdict"] == "BLOCKED"
    assert not any(artifact["derived_flags"].values())
    assert artifact["safety"]["current_constituents_used_as_historical_pit"] is False


def test_unknown_status_is_rejected():
    with pytest.raises(ValueError, match="Invalid foundation gate status"):
        build_foundation_certification(
            gates={"PIT": {"status": "UNKNOWN", "reason": "not checked"}},
            generated_at="2026-09-06T00:00:00Z",
        )


def test_manifest_validation_fails_closed():
    with pytest.raises(ValueError, match="Incomplete lineage manifest"):
        validate_manifest({"status": "COMPLETE", "source": "x"}, ("source", "coverage", "content_hash"))


def test_realtime_paper_requires_passing_artifact(tmp_path):
    path = tmp_path / "foundation.json"
    path.write_text('{"final_verdict":"BLOCKED","derived_flags":{"CAN_RUN_REAL_TIME_PAPER":false}}', encoding="utf-8")
    with pytest.raises(PermissionError):
        require_realtime_paper_certification(path)

    path.write_text(__import__("json").dumps(build_foundation_certification(
        gates=_all_pass(), generated_at="2026-09-06T00:00:00Z"
    )), encoding="utf-8")
    assert require_realtime_paper_certification(path)["final_verdict"] == "PASS"
