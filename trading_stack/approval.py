"""External Human / Board approval contract, cryptographic verification, and binding.

The algo-trading repository only VERIFIES external approval evidence signed
by authorized human or board authorities via asymmetric cryptography (Ed25519).
It never self-mints approvals for live trading.
"""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from cryptography.hazmat.primitives.asymmetric import ed25519
import pandas as pd
import yaml


class ApprovalAuthorityType(StrEnum):
    HUMAN = "HUMAN"
    BOARD = "BOARD"


class ApprovalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


PERMITTED_APPROVER_TYPES = frozenset({ApprovalAuthorityType.HUMAN.value, ApprovalAuthorityType.BOARD.value})
PERMITTED_APPROVAL_TYPES = frozenset({
    "HUMAN_BOARD",
    "PAPER_TRADING_AUTHORIZATION",
    "PROMOTION_TO_PAPER",
})


@dataclass(frozen=True, slots=True)
class TrustedIssuer:
    """Trusted public key configuration for an approval authority."""

    issuer_name: str
    issuer_type: str
    public_key_ed25519_base64: str
    status: str = "ACTIVE"
    valid_from: datetime | None = None
    expires_at: datetime | None = None


def load_trusted_issuers(config_path: Path | str | None = None) -> dict[str, TrustedIssuer]:
    """Load trusted public keys from YAML configuration."""
    if config_path is None:
        config_path = Path(__file__).resolve().parents[1] / "config" / "trusted_issuers.yaml"
    path = Path(config_path)
    if not path.exists():
        return {}
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(content, dict):
        return {}
    issuers_data = content.get("issuers", {})
    if not isinstance(issuers_data, dict):
        return {}
    result: dict[str, TrustedIssuer] = {}
    for key_id, item in issuers_data.items():
        if not isinstance(item, dict):
            continue
        vf = item.get("valid_from")
        exp = item.get("expires_at")
        vf_dt = pd.Timestamp(vf).to_pydatetime() if vf else None
        exp_dt = pd.Timestamp(exp).to_pydatetime() if exp else None
        if vf_dt and vf_dt.tzinfo is None:
            vf_dt = vf_dt.replace(tzinfo=timezone.utc)
        if exp_dt and exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        result[str(key_id)] = TrustedIssuer(
            issuer_name=str(item.get("issuer_name", "")),
            issuer_type=str(item.get("issuer_type", "")),
            public_key_ed25519_base64=str(item.get("public_key_ed25519_base64", "")),
            status=str(item.get("status", "ACTIVE")).upper().strip(),
            valid_from=vf_dt,
            expires_at=exp_dt,
        )
    return result


CANONICAL_PAYLOAD_KEYS = (
    "approval_id",
    "approval_type",
    "approved_at",
    "approved_by_identifier",
    "approved_by_type",
    "approved_stage",
    "code_sha",
    "evidence_hash",
    "expires_at",
    "foundation_certification_id",
    "issuer_key_id",
    "promotion_review_id",
    "requested_stage",
    "risk_policy_hash",
    "risk_policy_id",
    "run_id",
    "scope",
    "status",
    "strategy_candidate_id",
    "strategy_name",
    "subject_type",
)


def _normalize_iso_utc(val: Any) -> str:
    """Normalize any datetime or timestamp string to UTC ISO-8601 format."""
    if isinstance(val, datetime):
        parsed = val
    else:
        try:
            ts = pd.Timestamp(val)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid approval datetime value: {val!r}") from exc
        if pd.isna(ts):
            raise ValueError(f"Approval datetime cannot be NaT: {val!r}")
        parsed = ts.to_pydatetime()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _parse_aware_datetime(value: Any, field_name: str) -> datetime:
    """Parse a required approval timestamp and reject malformed or missing time."""
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise PermissionError(f"Approval field '{field_name}' is not a valid timestamp") from exc
    if pd.isna(ts):
        raise PermissionError(f"Approval field '{field_name}' cannot be NaT")
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.to_pydatetime()


def compute_canonical_payload_bytes(data: ExternalApprovalEvidence | Mapping[str, Any]) -> bytes:
    """Deterministic canonical JSON serialization of every signed field."""
    raw = data.to_dict() if isinstance(data, ExternalApprovalEvidence) else dict(data)
    canonical: dict[str, Any] = {}
    for k in CANONICAL_PAYLOAD_KEYS:
        val = raw.get(k)
        if val is None:
            canonical[k] = None
        elif k in {"approved_at", "expires_at"}:
            canonical[k] = _normalize_iso_utc(val)
        else:
            canonical[k] = str(val)
    return json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_approval_payload(
    payload_or_evidence: ExternalApprovalEvidence | Mapping[str, Any],
    private_key: ed25519.Ed25519PrivateKey,
) -> str:
    """Produce base64-encoded Ed25519 signature over canonical payload bytes."""
    payload_bytes = compute_canonical_payload_bytes(payload_or_evidence)
    signature_bytes = private_key.sign(payload_bytes)
    return base64.b64encode(signature_bytes).decode("utf-8")


def verify_approval_signature(
    data: Mapping[str, Any],
    trusted_issuers: Mapping[str, TrustedIssuer] | None = None,
    as_of_time: datetime | None = None,
) -> None:
    """Verify digital signature using trusted public keys."""
    issuer_key_id = data.get("issuer_key_id")
    if not issuer_key_id or str(issuer_key_id).strip() == "":
        raise PermissionError("Approval evidence missing or empty required field 'issuer_key_id'")

    signature_b64 = data.get("signature")
    if not signature_b64 or str(signature_b64).strip() == "":
        raise PermissionError("Approval evidence missing or empty required field 'signature'")

    if trusted_issuers is None:
        trusted_issuers = load_trusted_issuers()

    issuer = trusted_issuers.get(str(issuer_key_id))
    if issuer is None:
        raise PermissionError(f"Unknown or untrusted approval issuer key ID: '{issuer_key_id}'")

    if issuer.status != "ACTIVE":
        raise PermissionError(f"Approval issuer key '{issuer_key_id}' is not active (status: '{issuer.status}')")

    now = as_of_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if issuer.valid_from is not None and now < issuer.valid_from:
        raise PermissionError(f"Approval issuer key '{issuer_key_id}' is not yet valid")

    if issuer.expires_at is not None and now >= issuer.expires_at:
        raise PermissionError(f"Approval issuer key '{issuer_key_id}' has expired")

    try:
        public_key_raw = base64.b64decode(issuer.public_key_ed25519_base64)
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(public_key_raw)
        sig_bytes = base64.b64decode(str(signature_b64), validate=True)
        payload_bytes = compute_canonical_payload_bytes(data)
        public_key.verify(sig_bytes, payload_bytes)
    except Exception as exc:
        raise PermissionError(
            f"Approval signature verification failed: invalid signature or tampered payload ({exc})"
        ) from exc


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
    issuer_key_id: str = ""
    signature: str = ""

    def compute_hash(self) -> str:
        """Compute deterministic SHA-256 over canonical approval payload fields."""
        return hashlib.sha256(compute_canonical_payload_bytes(self)).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["approved_at"] = self.approved_at.isoformat() if hasattr(self.approved_at, "isoformat") else str(self.approved_at)
        d["expires_at"] = self.expires_at.isoformat() if hasattr(self.expires_at, "isoformat") else str(self.expires_at)
        d["approved_by_type"] = str(self.approved_by_type)
        d["status"] = str(self.status)
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
        expected_risk_policy_id: str | None = None,
        expected_risk_policy_hash: str | None = None,
        expected_code_sha: str | None = None,
        expected_evidence_hash: str | None = None,
        expected_scope: str | None = None,
        expected_subject_type: str | None = None,
        expected_promotion_review_id: str | None = None,
        trusted_issuers: Mapping[str, TrustedIssuer] | None = None,
        as_of_time: datetime | None = None,
    ) -> None:
        """Verify that external approval evidence is genuine, valid, matching, active, and cryptographically signed."""
        data = evidence.to_dict() if isinstance(evidence, ExternalApprovalEvidence) else dict(evidence)

        # 0. Completeness and required fields check
        required_fields = [
            "approval_id",
            "approval_type",
            "subject_type",
            "run_id",
            "strategy_name",
            "requested_stage",
            "approved_stage",
            "approved_by_type",
            "approved_by_identifier",
            "approved_at",
            "expires_at",
            "scope",
            "status",
            "foundation_certification_id",
            "risk_policy_id",
            "risk_policy_hash",
            "code_sha",
            "evidence_hash",
            "promotion_review_id",
            "issuer_key_id",
            "signature",
        ]
        for field in required_fields:
            val = data.get(field)
            if val is None or str(val).strip() == "":
                raise PermissionError(f"Approval evidence missing or empty required field '{field}'")

        # 1. Authority validation
        approver_type = str(data.get("approved_by_type", "")).upper().strip()
        if approver_type not in PERMITTED_APPROVER_TYPES:
            raise PermissionError(
                f"Invalid approval authority '{approver_type}'; must be an external HUMAN or BOARD authority"
            )

        approval_type = str(data.get("approval_type", "")).upper().strip()
        if approval_type not in PERMITTED_APPROVAL_TYPES:
            raise PermissionError(
                f"Invalid approval_type '{approval_type}'; expected a recognized human/board approval type"
            )

        identifier = str(data.get("approved_by_identifier", "")).strip()
        tokens = set(re.findall(r"[a-z0-9]+", identifier.lower()))
        disallowed = {"ai", "model", "agent", "system", "auto", "bot", "algorithm", "llm"}
        if not identifier or bool(tokens & disallowed):
            raise PermissionError(
                f"Approval cannot be issued by an automated agent or system identifier: '{identifier}'"
            )

        # 2. Status validation (must be ACTIVE, not REVOKED/PENDING/EXPIRED)
        status = str(data.get("status", "")).upper().strip()
        if status != ApprovalStatus.ACTIVE.value:
            raise PermissionError(f"Approval is not active (status: '{status}')")

        # 3. Cryptographic signature verification
        verify_approval_signature(data, trusted_issuers=trusted_issuers, as_of_time=as_of_time)
        issuer_registry = trusted_issuers if trusted_issuers is not None else load_trusted_issuers()
        issuer = issuer_registry.get(str(data.get("issuer_key_id")))
        if issuer is None or issuer.issuer_type.upper().strip() != approver_type:
            raise PermissionError(
                f"Approval issuer type does not match approved_by_type '{approver_type}'"
            )

        # 4. Target matching
        if str(data.get("run_id")) != expected_run_id:
            raise PermissionError(
                f"Approval run_id '{data.get('run_id')}' does not match expected '{expected_run_id}'"
            )
        if str(data.get("strategy_name")) != expected_strategy_name:
            raise PermissionError(
                f"Approval strategy_name '{data.get('strategy_name')}' does not match expected '{expected_strategy_name}'"
            )

        expected_stage_upper = expected_stage.upper().strip()
        requested_stage = str(data.get("requested_stage", "")).upper().strip()
        approved_stage = str(data.get("approved_stage", "")).upper().strip()
        if requested_stage != approved_stage:
            raise PermissionError(
                f"Requested stage '{requested_stage}' does not match approved stage '{approved_stage}'"
            )
        if approved_stage != expected_stage_upper:
            raise PermissionError(
                f"Approved stage '{approved_stage}' does not authorize target stage '{expected_stage}'"
            )

        if expected_subject_type:
            subject_type = str(data.get("subject_type", "")).strip()
            if subject_type != expected_subject_type:
                raise PermissionError(
                    f"Approval subject_type '{subject_type}' does not match expected '{expected_subject_type}'"
                )

        if expected_scope:
            scope = str(data.get("scope", "")).strip()
            if scope != expected_scope:
                raise PermissionError(
                    f"Approval scope '{scope}' does not match expected '{expected_scope}'"
                )

        # 5. Certification, Policy, Code, and Evidence binding
        if expected_foundation_cert_id:
            cert_id = str(data.get("foundation_certification_id", ""))
            if cert_id != expected_foundation_cert_id:
                raise PermissionError(
                    f"Approval foundation certification '{cert_id}' does not match active '{expected_foundation_cert_id}'"
                )

        if expected_risk_policy_id:
            risk_policy_id = str(data.get("risk_policy_id", ""))
            if risk_policy_id != expected_risk_policy_id:
                raise PermissionError(
                    f"Approval risk policy id '{risk_policy_id}' does not match active '{expected_risk_policy_id}'"
                )

        if expected_risk_policy_hash:
            risk_hash = str(data.get("risk_policy_hash", ""))
            if risk_hash != expected_risk_policy_hash:
                raise PermissionError(
                    f"Approval risk policy hash '{risk_hash}' does not match active '{expected_risk_policy_hash}'"
                )

        if expected_code_sha:
            code_sha = str(data.get("code_sha", ""))
            if code_sha != expected_code_sha:
                raise PermissionError(
                    f"Approval code_sha '{code_sha}' does not match expected '{expected_code_sha}'"
                )

        if expected_evidence_hash:
            evidence_hash = str(data.get("evidence_hash", ""))
            if evidence_hash != expected_evidence_hash:
                raise PermissionError(
                    f"Approval evidence_hash '{evidence_hash}' does not match expected '{expected_evidence_hash}'"
                )

        if expected_promotion_review_id:
            review_id = str(data.get("promotion_review_id", ""))
            if review_id != expected_promotion_review_id:
                raise PermissionError(
                    f"Approval promotion_review_id '{review_id}' does not match review '{expected_promotion_review_id}'"
                )

        # 6. Temporal check: approved_at <= now < expires_at, and approved_at < expires_at
        now = as_of_time or datetime.now(timezone.utc)
        now = _parse_aware_datetime(now, "as_of_time")
        approved_at = _parse_aware_datetime(data.get("approved_at"), "approved_at")

        if approved_at > now:
            raise PermissionError(
                f"Approval approved_at '{approved_at.isoformat()}' is in the future (current time: {now.isoformat()})"
            )

        expires_at = _parse_aware_datetime(data.get("expires_at"), "expires_at")

        if expires_at <= approved_at:
            raise PermissionError(
                f"Approval expiry '{expires_at.isoformat()}' must be strictly after approval time '{approved_at.isoformat()}'"
            )

        if now >= expires_at:
            raise PermissionError(f"Approval expired at {expires_at.isoformat()} (current time: {now.isoformat()})")

    @classmethod
    def record_approval(cls, conn: Any, approval: ExternalApprovalEvidence) -> None:
        """Persist externally-minted approval evidence into external_approval_evidence table."""
        raw_conn = getattr(conn, "conn", conn)
        if not approval.issuer_key_id or not approval.signature:
            raise PermissionError("Cannot record approval without issuer_key_id and signature")
        try:
            signature_bytes = base64.b64decode(approval.signature, validate=True)
        except Exception as exc:
            raise PermissionError("Cannot record approval with malformed signature encoding") from exc
        if len(signature_bytes) != 64:
            raise PermissionError("Cannot record approval with an invalid Ed25519 signature length")
        existing = raw_conn.execute(
            "SELECT approval_id FROM external_approval_evidence WHERE approval_id = ?",
            [approval.approval_id],
        ).fetchone()
        if existing is not None:
            raise ValueError(f"Approval '{approval.approval_id}' already exists; approvals are append-only")

        query = """
            INSERT INTO external_approval_evidence (
                approval_id, approval_type, subject_type, strategy_candidate_id,
                run_id, strategy_name, requested_stage, approved_stage, approved_by_type,
                approved_by_identifier, approved_at, expires_at, scope, status,
                foundation_certification_id, risk_policy_id, risk_policy_hash,
                promotion_review_id, code_sha, evidence_hash, issuer_key_id, signature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                approval.approved_at.isoformat() if hasattr(approval.approved_at, "isoformat") else str(approval.approved_at),
                approval.expires_at.isoformat() if hasattr(approval.expires_at, "isoformat") else str(approval.expires_at),
                approval.scope,
                str(approval.status),
                approval.foundation_certification_id,
                approval.risk_policy_id,
                approval.risk_policy_hash,
                approval.promotion_review_id,
                approval.code_sha,
                approval.evidence_hash,
                approval.issuer_key_id,
                approval.signature,
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
                   promotion_review_id, code_sha, evidence_hash, issuer_key_id, signature
            FROM external_approval_evidence
            WHERE run_id = ? AND strategy_name = ? AND status = 'ACTIVE'
            ORDER BY approved_at DESC LIMIT 1
        """
        try:
            row = raw_conn.execute(query, [run_id, strategy_name]).fetchone()
        except Exception:
            return None
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
            issuer_key_id=str(row[20] or ""),
            signature=str(row[21] or ""),
        )
