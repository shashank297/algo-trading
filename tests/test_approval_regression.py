"""Regression tests for external human/board approval verification boundaries."""

from datetime import datetime, timedelta, timezone
import pytest
from trading_stack.approval import ExternalApprovalVerifier


def make_valid_approval_dict(
    approved_stage: str = "PAPER_CANDIDATE",
    expires_in_hours: int = 24,
    strategy_name: str = "TestStrategy",
    run_id: str = "run-123",
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "approval_id": "appr-001",
        "approval_type": "HUMAN_BOARD",
        "subject_type": "STRATEGY_CANDIDATE",
        "strategy_candidate_id": "cand-001",
        "run_id": run_id,
        "strategy_name": strategy_name,
        "requested_stage": approved_stage,
        "approved_stage": approved_stage,
        "approved_by_type": "HUMAN",
        "approved_by_identifier": "risk_officer_alice",
        "approved_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=expires_in_hours)).isoformat(),
        "scope": "PAPER_TRADING_SINGLE_RUN",
        "status": "ACTIVE",
        "foundation_certification_id": "cert-123",
        "risk_policy_hash": "hash-abc",
        "code_sha": "sha-456",
        "evidence_hash": "ev-789",
    }


def test_candidate_approval_cannot_authorize_paper_active():
    """An approval granted only for PAPER_CANDIDATE must NOT authorize PAPER_ACTIVE execution."""
    data = make_valid_approval_dict(approved_stage="PAPER_CANDIDATE")

    # In defective code, this passes because 'PAPER_CANDIDATE' is hardcoded in the allowed set.
    # In fixed code, this MUST raise PermissionError.
    with pytest.raises(PermissionError, match="does not authorize target stage"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_ACTIVE",
        )


def test_ai_or_bot_identifier_rejected():
    data = make_valid_approval_dict()
    data["approved_by_identifier"] = "auto_agent_bot"
    with pytest.raises(PermissionError, match="automated agent or system identifier"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
        )


def test_expired_approval_rejected():
    now = datetime.now(timezone.utc)
    data = make_valid_approval_dict()
    data["approved_at"] = (now - timedelta(days=2)).isoformat()
    data["expires_at"] = (now - timedelta(days=1)).isoformat()
    with pytest.raises(PermissionError, match="Approval expired"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
        )


def test_mismatched_run_id_rejected():
    data = make_valid_approval_dict(run_id="run-different")
    with pytest.raises(PermissionError, match="does not match expected"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
        )


def test_mismatched_risk_policy_hash_rejected():
    data = make_valid_approval_dict()
    with pytest.raises(PermissionError, match="risk policy hash"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            expected_risk_policy_hash="different-risk-hash",
        )


def test_missing_required_field_rejected():
    data = make_valid_approval_dict()
    del data["code_sha"]
    with pytest.raises(PermissionError, match="missing or empty required field 'code_sha'"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
        )


def test_future_approval_rejected():
    data = make_valid_approval_dict()
    future_time = datetime.now(timezone.utc) + timedelta(days=1)
    data["approved_at"] = future_time.isoformat()
    data["expires_at"] = (future_time + timedelta(days=2)).isoformat()
    with pytest.raises(PermissionError, match="is in the future"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
        )


def test_expiry_before_approved_at_rejected():
    data = make_valid_approval_dict()
    now = datetime.now(timezone.utc)
    data["approved_at"] = now.isoformat()
    data["expires_at"] = (now - timedelta(hours=1)).isoformat()
    with pytest.raises(PermissionError, match="must be strictly after approval time"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
        )


def test_revoked_status_rejected():
    data = make_valid_approval_dict()
    data["status"] = "REVOKED"
    with pytest.raises(PermissionError, match="Approval is not active"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
        )


def test_bound_code_sha_mismatch_rejected():
    data = make_valid_approval_dict()
    with pytest.raises(PermissionError, match="Approval code_sha"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            expected_code_sha="different-code-sha",
        )


def test_bound_evidence_hash_mismatch_rejected():
    data = make_valid_approval_dict()
    with pytest.raises(PermissionError, match="Approval evidence_hash"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            expected_evidence_hash="different-evidence-hash",
        )


def test_scope_mismatch_rejected():
    data = make_valid_approval_dict()
    with pytest.raises(PermissionError, match="Approval scope"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            expected_scope="DIFFERENT_SCOPE",
        )


def test_valid_approval_passes():
    """Verify that a well-formed, valid approval passes all checks without error."""
    data = make_valid_approval_dict(approved_stage="PAPER_CANDIDATE")
    ExternalApprovalVerifier.verify_approval(
        data,
        expected_run_id="run-123",
        expected_strategy_name="TestStrategy",
        expected_stage="PAPER_CANDIDATE",
        expected_risk_policy_hash="hash-abc",
        expected_code_sha="sha-456",
        expected_evidence_hash="ev-789",
        expected_foundation_cert_id="cert-123",
        expected_scope="PAPER_TRADING_SINGLE_RUN",
    )
