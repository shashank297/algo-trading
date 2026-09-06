"""External Human / Board approval contract and verification.

The algo-trading repository only VERIFIES external approval evidence signed
by authorized human or board authorities. It never self-mints approvals.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping

import pandas as pd


class ApprovalAuthorityType(StrEnum):
    HUMAN = "HUMAN"
    BOARD = "BOARD"


class ApprovalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


PERMITTED_APPROVER_TYPES = frozenset({ApprovalAuthorityType.HUMAN.value, ApprovalAuthorityType.BOARD.value})


@dataclass(frozen=True, slots=True)
class ExternalApprovalEvidence:
    """Immutable external approval evidence artifact."""

    approval_id: str
    approval_type: str
    subject_type: str
    run_id: str
    strategy_name: str
    requested_stage: str
    approved_stage: str
    approved_by_type: ApprovalAuthorityType | str
    approved_by_identifier: str
    approved_at: datetime
    expires_at: datetime
    scope: str
    status: ApprovalStatus | str
    foundation_certification_id: str
    risk_policy_id: str
    risk_policy_hash: str
    code_sha: str
    evidence_hash: str
    strategy_candidate_id: str | None = None
    promotion_review_id: str | None = None

    def compute_hash(self) -> str:
        """Compute deterministic SHA-256 over all approval payload fields."""
        payload = asdict(self)
        payload.pop("approval_id", None)
        payload["approved_at"] = self.approved_at.isoformat() if hasattr(self.approved_at, "isoformat") else str(self.approved_at)
        payload["expires_at"] = self.expires_at.isoformat() if hasattr(self.expires_at, "isoformat") else str(self.expires_at)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["approved_at"] = self.approved_at.isoformat() if hasattr(self.approved_at, "isoformat") else str(self.approved_at)
        d["expires_at"] = self.expires_at.isoformat() if hasattr(self.expires_at, "isoformat") else str(self.expires_at)
        return d


class ExternalApprovalVerifier:
    """Strict fail-closed verification of external human / board approval evidence."""

    @classmethod
    def verify_approval(
        cls,
        evidence: ExternalApprovalEvidence | Mapping[str, Any],
        *,
        expected_run_id: str,
        expected_strategy_name: str,
        expected_stage: str = "PAPER_CANDIDATE",
        expected_foundation_cert_id: str | None = None,
        expected_risk_policy_hash: str | None = None,
        as_of_time: datetime | None = None,
    ) -> None:
        """Verify that external approval evidence is genuine, valid, matching, and active."""
        data = evidence.to_dict() if isinstance(evidence, ExternalApprovalEvidence) else dict(evidence)

        # 1. Authority validation
        approver_type = str(data.get("approved_by_type", "")).upper().strip()
        if approver_type not in PERMITTED_APPROVER_TYPES:
            raise PermissionError(
                f"Invalid approval authority '{approver_type}'; must be an external HUMAN or BOARD authority"
            )

        import re
        identifier = str(data.get("approved_by_identifier", "")).strip()
        tokens = set(re.findall(r"[a-z0-9]+", identifier.lower()))
        disallowed = {"ai", "model", "agent", "system", "auto", "bot", "algorithm", "llm"}
        if not identifier or bool(tokens & disallowed):
            raise PermissionError(
                f"Approval cannot be issued by an automated agent or system identifier: '{identifier}'"
            )

        # 2. Status validation
        status = str(data.get("status", "")).upper().strip()
        if status != ApprovalStatus.ACTIVE.value:
            raise PermissionError(f"Approval is not active (status: '{status}')")

        # 3. Target matching
        if str(data.get("run_id")) != expected_run_id:
            raise PermissionError(
                f"Approval run_id '{data.get('run_id')}' does not match expected '{expected_run_id}'"
            )
        if str(data.get("strategy_name")) != expected_strategy_name:
            raise PermissionError(
                f"Approval strategy_name '{data.get('strategy_name')}' does not match expected '{expected_strategy_name}'"
            )

        approved_stage = str(data.get("approved_stage", "")).upper().strip()
        if approved_stage not in {expected_stage.upper(), "PAPER_ACTIVE", "PAPER_CANDIDATE"}:
            raise PermissionError(
                f"Approved stage '{approved_stage}' does not authorize target stage '{expected_stage}'"
            )

        # 4. Certification and Policy binding
        if expected_foundation_cert_id:
            cert_id = str(data.get("foundation_certification_id", ""))
            if cert_id != expected_foundation_cert_id:
                raise PermissionError(
                    f"Approval foundation certification '{cert_id}' does not match active '{expected_foundation_cert_id}'"
                )

        if expected_risk_policy_hash:
            risk_hash = str(data.get("risk_policy_hash", ""))
            if risk_hash != expected_risk_policy_hash:
                raise PermissionError(
                    f"Approval risk policy hash '{risk_hash}' does not match active '{expected_risk_policy_hash}'"
                )

        # 5. Expiration check
        now = as_of_time or datetime.now(timezone.utc)
        expires_at_raw = data.get("expires_at")
        expires_at = (
            expires_at_raw
            if isinstance(expires_at_raw, datetime)
            else pd.Timestamp(expires_at_raw).to_pydatetime()
        )
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        if now > expires_at:
            raise PermissionError(f"Approval expired at {expires_at.isoformat()} (current time: {now.isoformat()})")

    @classmethod
    def record_approval(cls, conn: Any, approval: ExternalApprovalEvidence) -> None:
        """Persist externally-minted approval evidence into external_approval_evidence table."""
        raw_conn = getattr(conn, "conn", conn)
        query = """
            INSERT OR REPLACE INTO external_approval_evidence (
                approval_id, approval_type, subject_type, strategy_candidate_id,
                run_id, strategy_name, requested_stage, approved_stage, approved_by_type,
                approved_by_identifier, approved_at, expires_at, scope, status,
                foundation_certification_id, risk_policy_id, risk_policy_hash,
                promotion_review_id, code_sha, evidence_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        raw_conn.execute(
            query,
            [
                approval.approval_id,
                approval.approval_type,
                approval.subject_type,
                approval.strategy_candidate_id,
                approval.run_id,
                approval.strategy_name,
                approval.requested_stage,
                approval.approved_stage,
                str(approval.approved_by_type),
                approval.approved_by_identifier,
                approval.approved_at.isoformat(),
                approval.expires_at.isoformat(),
                approval.scope,
                str(approval.status),
                approval.foundation_certification_id,
                approval.risk_policy_id,
                approval.risk_policy_hash,
                approval.promotion_review_id,
                approval.code_sha,
                approval.evidence_hash,
            ],
        )

    @classmethod
    def load_active_approval(cls, conn: Any, run_id: str, strategy_name: str) -> ExternalApprovalEvidence | None:
        """Load the latest active approval evidence for a run, if any exists."""
        raw_conn = getattr(conn, "conn", conn)
        query = """
            SELECT approval_id, approval_type, subject_type, strategy_candidate_id,
                   run_id, strategy_name, requested_stage, approved_stage, approved_by_type,
                   approved_by_identifier, approved_at, expires_at, scope, status,
                   foundation_certification_id, risk_policy_id, risk_policy_hash,
                   promotion_review_id, code_sha, evidence_hash
            FROM external_approval_evidence
            WHERE run_id = ? AND strategy_name = ? AND status = 'ACTIVE'
            ORDER BY approved_at DESC LIMIT 1
        """
        row = raw_conn.execute(query, [run_id, strategy_name]).fetchone()
        if not row:
            return None
        return ExternalApprovalEvidence(
            approval_id=row[0],
            approval_type=row[1],
            subject_type=row[2],
            strategy_candidate_id=row[3],
            run_id=row[4],
            strategy_name=row[5],
            requested_stage=row[6],
            approved_stage=row[7],
            approved_by_type=ApprovalAuthorityType(row[8]),
            approved_by_identifier=row[9],
            approved_at=pd.Timestamp(row[10]).to_pydatetime(),
            expires_at=pd.Timestamp(row[11]).to_pydatetime(),
            scope=row[12],
            status=ApprovalStatus(row[13]),
            foundation_certification_id=row[14],
            risk_policy_id=row[15],
            risk_policy_hash=row[16],
            promotion_review_id=row[17],
            code_sha=row[18],
            evidence_hash=row[19],
        )
