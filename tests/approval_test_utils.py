"""Ephemeral signed approval fixtures for paper-session integration tests."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ed25519

from risk.factory import load_canonical_risk_policy
from storage.duckdb_manager import DuckDBManager
from trading_stack.approval import (
    ApprovalAuthorityType,
    ApprovalStatus,
    ExternalApprovalEvidence,
    ExternalApprovalVerifier,
    TrustedIssuer,
    sign_approval_payload,
)


_PRIVATE_KEY = ed25519.Ed25519PrivateKey.generate()
_PUBLIC_KEY_B64 = base64.b64encode(_PRIVATE_KEY.public_key().public_bytes_raw()).decode("utf-8")
TEST_ISSUER_KEY_ID = "ephemeral-test-board"
TEST_TRUSTED_ISSUERS = {
    TEST_ISSUER_KEY_ID: TrustedIssuer(
        issuer_name="Ephemeral test board",
        issuer_type="BOARD",
        public_key_ed25519_base64=_PUBLIC_KEY_B64,
        status="ACTIVE",
        valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2035, 1, 1, tzinfo=timezone.utc),
    ),
}


def seed_signed_paper_approval(
    db: DuckDBManager,
    *,
    run_id: str,
    strategy_name: str,
    review_id: str,
    stage: str = "PAPER_ACTIVE",
    code_sha: str = "0" * 40,
    evidence_hash: str = "0" * 64,
) -> dict[str, Any]:
    """Seed only the disposable DB context needed by PromotionEngine."""
    policy = load_canonical_risk_policy()
    db.conn.execute(
        """
        INSERT INTO strategy_runs (
            run_id, strategy_name, asset_class, symbol, timeframe, mode,
            parameters_json, data_hash, status, started_at, notes, frame_certification_id
        ) VALUES (?, ?, 'EQUITY', 'TEST-EQ', '1d', 'BACKTEST', '{}', ?, 'COMPLETED', CURRENT_TIMESTAMP, '{}', ?)
        """,
        [run_id, strategy_name, evidence_hash, f"frame-{run_id}"],
    )
    db.conn.execute(
        """
        INSERT INTO foundation_certifications (
            foundation_certification_id, artifact_version, generated_at, status,
            code_sha, lineage_status, risk_policy_id, risk_policy_hash,
            gates_json, derived_flags_json, artifact_sha256, artifact_json, is_active
        ) VALUES (?, 'test', CURRENT_TIMESTAMP, 'PASS', ?, 'PASS', ?, ?, '[]', '{}', ?, '{}', true)
        """,
        [
            f"foundation-{run_id}", code_sha, policy.policy_id, policy.policy_hash,
            f"foundation-hash-{run_id}",
        ],
    )
    now = datetime.now(timezone.utc)
    payload = {
        "approval_id": f"approval-{run_id}",
        "approval_type": "PROMOTION_TO_PAPER",
        "subject_type": "STRATEGY_RUN",
        "strategy_candidate_id": f"candidate-{run_id}",
        "run_id": run_id,
        "strategy_name": strategy_name,
        "requested_stage": stage,
        "approved_stage": stage,
        "approved_by_type": "BOARD",
        "approved_by_identifier": "ephemeral_test_board",
        "approved_at": (now - timedelta(hours=1)).isoformat(),
        "expires_at": (now + timedelta(days=7)).isoformat(),
        "scope": "PAPER_TRADING",
        "status": "ACTIVE",
        "foundation_certification_id": f"foundation-{run_id}",
        "risk_policy_id": policy.policy_id,
        "risk_policy_hash": policy.policy_hash,
        "promotion_review_id": review_id,
        "code_sha": code_sha,
        "evidence_hash": evidence_hash,
        "issuer_key_id": TEST_ISSUER_KEY_ID,
    }
    payload["signature"] = sign_approval_payload(payload, _PRIVATE_KEY)
    evidence = ExternalApprovalEvidence(
        **{
            **payload,
            "approved_by_type": ApprovalAuthorityType.BOARD,
            "status": ApprovalStatus.ACTIVE,
            "approved_at": now - timedelta(hours=1),
            "expires_at": now + timedelta(days=7),
        }
    )
    ExternalApprovalVerifier.record_approval(db.conn, evidence)
    return TEST_TRUSTED_ISSUERS
