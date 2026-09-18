"""Regression tests for external human/board approval cryptographic verification and binding."""

import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ed25519
import pytest

from storage.duckdb_manager import DuckDBManager
from trading_stack.approval import (
    ApprovalAuthorityType,
    ApprovalStatus,
    ExternalApprovalEvidence,
    ExternalApprovalVerifier,
    TrustedIssuer,
    sign_approval_payload,
)
from trading_stack.promotion import PromotionEngine
from risk.factory import load_canonical_risk_policy


@pytest.fixture
def test_keypair():
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    pub_b64 = base64.b64encode(public_key.public_bytes_raw()).decode("utf-8")
    return private_key, pub_b64


@pytest.fixture
def test_trusted_issuers(test_keypair):
    _, pub_b64 = test_keypair
    return {
        "test-issuer-1": TrustedIssuer(
            issuer_name="Risk Committee Test",
            issuer_type="BOARD",
            public_key_ed25519_base64=pub_b64,
            status="ACTIVE",
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        ),
        "test-issuer-expired": TrustedIssuer(
            issuer_name="Expired Signer",
            issuer_type="BOARD",
            public_key_ed25519_base64=pub_b64,
            status="ACTIVE",
            valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
        ),
        "test-issuer-revoked": TrustedIssuer(
            issuer_name="Revoked Signer",
            issuer_type="BOARD",
            public_key_ed25519_base64=pub_b64,
            status="REVOKED",
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        ),
    }


def make_signed_approval_dict(
    test_keypair,
    approved_stage: str = "PAPER_CANDIDATE",
    expires_in_hours: int = 24,
    strategy_name: str = "TestStrategy",
    run_id: str = "run-123",
    issuer_key_id: str = "test-issuer-1",
) -> dict:
    private_key, _ = test_keypair
    now = datetime.now(timezone.utc)
    data = {
        "approval_id": "appr-001",
        "approval_type": "HUMAN_BOARD",
        "subject_type": "STRATEGY_RUN",
        "strategy_candidate_id": "cand-001",
        "run_id": run_id,
        "strategy_name": strategy_name,
        "requested_stage": approved_stage,
        "approved_stage": approved_stage,
        "approved_by_type": "BOARD",
        "approved_by_identifier": "risk_officer_alice",
        "approved_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=expires_in_hours)).isoformat(),
        "scope": "PAPER_TRADING_SINGLE_RUN",
        "status": "ACTIVE",
        "foundation_certification_id": "cert-123",
        "risk_policy_id": "risk-v1",
        "risk_policy_hash": "hash-abc",
        "code_sha": "sha-456",
        "evidence_hash": "ev-789",
        "promotion_review_id": "rev-001",
        "issuer_key_id": issuer_key_id,
    }
    sig = sign_approval_payload(data, private_key)
    data["signature"] = sig
    return data


def test_candidate_approval_cannot_authorize_paper_active(test_keypair, test_trusted_issuers):
    """An approval granted only for PAPER_CANDIDATE must NOT authorize PAPER_ACTIVE execution."""
    data = make_signed_approval_dict(test_keypair, approved_stage="PAPER_CANDIDATE")
    with pytest.raises(PermissionError, match="does not authorize target stage"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_ACTIVE",
            trusted_issuers=test_trusted_issuers,
        )


def test_ai_or_bot_identifier_rejected(test_keypair, test_trusted_issuers):
    data = make_signed_approval_dict(test_keypair)
    data["approved_by_identifier"] = "auto_agent_bot"
    with pytest.raises(PermissionError, match="automated agent or system identifier"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            trusted_issuers=test_trusted_issuers,
        )


def test_expired_approval_rejected(test_keypair, test_trusted_issuers):
    private_key, _ = test_keypair
    now = datetime.now(timezone.utc)
    data = make_signed_approval_dict(test_keypair)
    data["approved_at"] = (now - timedelta(days=2)).isoformat()
    data["expires_at"] = (now - timedelta(days=1)).isoformat()
    data["signature"] = sign_approval_payload(data, private_key)
    with pytest.raises(PermissionError, match="Approval expired"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            trusted_issuers=test_trusted_issuers,
        )


def test_future_approval_rejected(test_keypair, test_trusted_issuers):
    private_key, _ = test_keypair
    future_time = datetime.now(timezone.utc) + timedelta(days=1)
    data = make_signed_approval_dict(test_keypair)
    data["approved_at"] = future_time.isoformat()
    data["expires_at"] = (future_time + timedelta(days=2)).isoformat()
    data["signature"] = sign_approval_payload(data, private_key)
    with pytest.raises(PermissionError, match="is in the future"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            trusted_issuers=test_trusted_issuers,
        )


def test_expiry_before_approved_at_rejected(test_keypair, test_trusted_issuers):
    private_key, _ = test_keypair
    now = datetime.now(timezone.utc)
    data = make_signed_approval_dict(test_keypair)
    data["approved_at"] = now.isoformat()
    data["expires_at"] = (now - timedelta(hours=1)).isoformat()
    data["signature"] = sign_approval_payload(data, private_key)
    with pytest.raises(PermissionError, match="must be strictly after approval time"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            trusted_issuers=test_trusted_issuers,
        )


def test_revoked_status_rejected(test_keypair, test_trusted_issuers):
    data = make_signed_approval_dict(test_keypair)
    data["status"] = "REVOKED"
    with pytest.raises(PermissionError, match="Approval is not active"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            trusted_issuers=test_trusted_issuers,
        )


def test_missing_required_field_rejected(test_keypair, test_trusted_issuers):
    data = make_signed_approval_dict(test_keypair)
    del data["code_sha"]
    with pytest.raises(PermissionError, match="missing or empty required field 'code_sha'"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            trusted_issuers=test_trusted_issuers,
        )


def test_mismatched_run_id_rejected(test_keypair, test_trusted_issuers):
    data = make_signed_approval_dict(test_keypair, run_id="run-different")
    with pytest.raises(PermissionError, match="does not match expected"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            trusted_issuers=test_trusted_issuers,
        )


def test_mismatched_risk_policy_hash_rejected(test_keypair, test_trusted_issuers):
    data = make_signed_approval_dict(test_keypair)
    with pytest.raises(PermissionError, match="risk policy hash"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            expected_risk_policy_hash="different-risk-hash",
            trusted_issuers=test_trusted_issuers,
        )


def test_bound_code_sha_mismatch_rejected(test_keypair, test_trusted_issuers):
    data = make_signed_approval_dict(test_keypair)
    with pytest.raises(PermissionError, match="Approval code_sha"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            expected_code_sha="different-code-sha",
            trusted_issuers=test_trusted_issuers,
        )


def test_bound_evidence_hash_mismatch_rejected(test_keypair, test_trusted_issuers):
    data = make_signed_approval_dict(test_keypair)
    with pytest.raises(PermissionError, match="Approval evidence_hash"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            expected_evidence_hash="different-evidence-hash",
            trusted_issuers=test_trusted_issuers,
        )


def test_scope_mismatch_rejected(test_keypair, test_trusted_issuers):
    data = make_signed_approval_dict(test_keypair)
    with pytest.raises(PermissionError, match="Approval scope"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            expected_scope="DIFFERENT_SCOPE",
            trusted_issuers=test_trusted_issuers,
        )


def test_subject_type_mismatch_rejected(test_keypair, test_trusted_issuers):
    data = make_signed_approval_dict(test_keypair)
    with pytest.raises(PermissionError, match="Approval subject_type"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            expected_subject_type="DIFFERENT_SUBJECT",
            trusted_issuers=test_trusted_issuers,
        )


def test_unknown_issuer_key_id_rejected(test_keypair, test_trusted_issuers):
    data = make_signed_approval_dict(test_keypair, issuer_key_id="untrusted-key-999")
    with pytest.raises(PermissionError, match="Unknown or untrusted approval issuer key ID"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            trusted_issuers=test_trusted_issuers,
        )


def test_expired_issuer_key_rejected(test_keypair, test_trusted_issuers):
    data = make_signed_approval_dict(test_keypair, issuer_key_id="test-issuer-expired")
    with pytest.raises(PermissionError, match="has expired"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            trusted_issuers=test_trusted_issuers,
        )


def test_revoked_issuer_key_rejected(test_keypair, test_trusted_issuers):
    data = make_signed_approval_dict(test_keypair, issuer_key_id="test-issuer-revoked")
    with pytest.raises(PermissionError, match="is not active"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            trusted_issuers=test_trusted_issuers,
        )


def test_tampered_payload_invalidates_signature(test_keypair, test_trusted_issuers):
    """If any field in the payload is modified after signing, signature verification must fail."""
    data = make_signed_approval_dict(test_keypair)
    # Alter code_sha without re-signing
    data["code_sha"] = "tampered-sha-0000"
    with pytest.raises(PermissionError, match="Approval signature verification failed"):
        ExternalApprovalVerifier.verify_approval(
            data,
            expected_run_id="run-123",
            expected_strategy_name="TestStrategy",
            expected_stage="PAPER_CANDIDATE",
            trusted_issuers=test_trusted_issuers,
        )


def test_valid_cryptographic_approval_passes(test_keypair, test_trusted_issuers):
    """Verify that a genuine, correctly signed approval passes all checks without error."""
    data = make_signed_approval_dict(test_keypair, approved_stage="PAPER_CANDIDATE")
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
        expected_subject_type="STRATEGY_RUN",
        trusted_issuers=test_trusted_issuers,
    )


def test_promotion_engine_assert_paper_authorized_strict_binding(tmp_path: Path, test_keypair, test_trusted_issuers, monkeypatch):
    """Verify PromotionEngine.assert_paper_authorized resolves and binds all 9 context fields fail-closed."""
    db = DuckDBManager(str(tmp_path / "promo_test.duckdb"))
    promo = PromotionEngine(db)

    # 1. Setup promotion review with PASS and human_approved=True
    db.conn.execute("""
        INSERT INTO promotion_reviews (
            review_id, strategy_name, run_id, stage, decision, score, reasons_json, human_approved, reviewed_at
        ) VALUES (
            'rev_ok', 'trend_following', 'run_001', 'PAPER_CANDIDATE', 'PASS', 1.0, '[]', true, CURRENT_TIMESTAMP
        );
    """)

    # 2. Setup strategy_runs with data_hash and frame_certification_id
    db.conn.execute("""
        INSERT INTO strategy_runs (
            run_id, strategy_name, asset_class, symbol, timeframe, mode,
            parameters_json, data_hash, status, started_at, notes, frame_certification_id
        ) VALUES (
            'run_001', 'trend_following', 'EQUITY', 'RELIANCE', '1d', 'BACKTEST',
            '{}', 'ev-data-hash-001', 'COMPLETED', CURRENT_TIMESTAMP, '{}', 'cert-foundation-001'
        );
    """)

    canonical_policy = load_canonical_risk_policy()
    db.conn.execute("""
        INSERT INTO foundation_certifications (
            foundation_certification_id, artifact_version, generated_at, status,
            code_sha, lineage_status, risk_policy_id, risk_policy_hash,
            gates_json, derived_flags_json, artifact_sha256, artifact_json, is_active
        ) VALUES (?, 'test', CURRENT_TIMESTAMP, 'PASS', ?, 'PASS', ?, ?, '[]', '{}', ?, '{}', true)
    """, [
        "cert-foundation-001",
        "sha-code-001",
        canonical_policy.policy_id,
        canonical_policy.policy_hash,
        "foundation-test-hash",
    ])

    # 3. Create properly signed approval evidence matching all 9 fields
    private_key, _ = test_keypair
    now = datetime.now(timezone.utc)
    evidence_dict = {
        "approval_id": "appr-001",
        "approval_type": "HUMAN_BOARD",
        "subject_type": "STRATEGY_RUN",
        "strategy_candidate_id": "cand-001",
        "run_id": "run_001",
        "strategy_name": "trend_following",
        "requested_stage": "PAPER_CANDIDATE",
        "approved_stage": "PAPER_CANDIDATE",
        "approved_by_type": "BOARD",
        "approved_by_identifier": "risk_officer_alice",
        "approved_at": now.isoformat(),
        "expires_at": (now + timedelta(days=7)).isoformat(),
        "scope": "PAPER_TRADING",
        "status": "ACTIVE",
        "foundation_certification_id": "cert-foundation-001",
        "risk_policy_id": canonical_policy.policy_id,
        "risk_policy_hash": canonical_policy.policy_hash,
        "code_sha": "sha-code-001",
        "evidence_hash": "ev-data-hash-001",
        "promotion_review_id": "rev_ok",
        "issuer_key_id": "test-issuer-1",
    }
    evidence_dict["signature"] = sign_approval_payload(evidence_dict, private_key)

    evidence = ExternalApprovalEvidence(
        approval_id=evidence_dict["approval_id"],
        approval_type=evidence_dict["approval_type"],
        subject_type=evidence_dict["subject_type"],
        strategy_candidate_id=evidence_dict["strategy_candidate_id"],
        run_id=evidence_dict["run_id"],
        strategy_name=evidence_dict["strategy_name"],
        requested_stage=evidence_dict["requested_stage"],
        approved_stage=evidence_dict["approved_stage"],
        approved_by_type=ApprovalAuthorityType.BOARD,
        approved_by_identifier=evidence_dict["approved_by_identifier"],
        approved_at=now,
        expires_at=now + timedelta(days=7),
        scope=evidence_dict["scope"],
        status=ApprovalStatus.ACTIVE,
        foundation_certification_id=evidence_dict["foundation_certification_id"],
        risk_policy_id=evidence_dict["risk_policy_id"],
        risk_policy_hash=evidence_dict["risk_policy_hash"],
        promotion_review_id=evidence_dict["promotion_review_id"],
        code_sha=evidence_dict["code_sha"],
        evidence_hash=evidence_dict["evidence_hash"],
        issuer_key_id=evidence_dict["issuer_key_id"],
        signature=evidence_dict["signature"],
    )

    ExternalApprovalVerifier.record_approval(db.conn, evidence)

    # 4. Successful authorization when all 9 fields match
    monkeypatch.setenv("CODE_SHA", "sha-code-001")
    promo.assert_paper_authorized(
        "run_001",
        "trend_following",
        expected_code_sha="sha-code-001",
        expected_risk_policy_hash=canonical_policy.policy_hash,
        expected_scope="PAPER_TRADING",
        expected_subject_type="STRATEGY_RUN",
        trusted_issuers=test_trusted_issuers,
    )

    # 5. Fail closed on code_sha mismatch
    with pytest.raises(PermissionError, match="Approval code_sha"):
        promo.assert_paper_authorized(
            "run_001",
            "trend_following",
            expected_code_sha="wrong-code-sha",
            expected_risk_policy_hash=canonical_policy.policy_hash,
            trusted_issuers=test_trusted_issuers,
        )

    # 6. Fail closed on evidence_hash mismatch
    with pytest.raises(PermissionError, match="Approval evidence_hash"):
        promo.assert_paper_authorized(
            "run_001",
            "trend_following",
            expected_code_sha="sha-code-001",
            expected_evidence_hash="wrong-evidence-hash",
            expected_risk_policy_hash=canonical_policy.policy_hash,
            trusted_issuers=test_trusted_issuers,
        )
