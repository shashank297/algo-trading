"""Fail-closed foundation certification and promotion prerequisites.

This module is deliberately independent of broker credentials and databases.  It
turns reviewed gate evidence into one deterministic artifact that downstream
promotion code can consume without treating UNKNOWN or NOT_RUN as success.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


GATE_STATUSES = frozenset({"PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE"})
REQUIRED_GATES = (
    "PIT",
    "LINEAGE",
    "TRANSACTION_COSTS",
    "ROBUSTNESS",
    "KPI",
    "RISK_CONFIGURATION",
    "INDEPENDENT_QA_RISK",
)


@dataclass(frozen=True)
class Gate:
    name: str
    status: str
    reason: str
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "evidence": list(self.evidence),
        }


def validate_manifest(manifest: Mapping[str, Any], required: tuple[str, ...]) -> None:
    """Reject incomplete lineage manifests; missing fields never default to PASS."""

    missing = [key for key in required if manifest.get(key) in (None, "", [], {})]
    if missing:
        raise ValueError("Incomplete lineage manifest: " + ", ".join(missing))
    if manifest.get("status") not in {"COMPLETE", "CERTIFIED"}:
        raise ValueError("Lineage manifest status must be COMPLETE or CERTIFIED")


def _gate(name: str, status: str, reason: str, *evidence: str) -> Gate:
    if status not in GATE_STATUSES:
        raise ValueError(f"Invalid foundation gate status: {status}")
    return Gate(name, status, reason, tuple(evidence))


def build_foundation_certification(
    *,
    gates: Mapping[str, Mapping[str, Any]],
    artifact_version: str = "foundation-certification-v1",
    generated_at: str,
) -> dict[str, Any]:
    """Build a canonical artifact and derive all capability flags deterministically."""

    normalized: list[dict[str, Any]] = []
    for name in REQUIRED_GATES:
        raw = gates.get(name)
        if not isinstance(raw, Mapping):
            gate = _gate(name, "BLOCKED", "No gate record supplied")
        else:
            status = str(raw.get("status", "BLOCKED"))
            reason = str(raw.get("reason", "No gate reason supplied"))
            evidence = tuple(str(item) for item in raw.get("evidence", ()))
            gate = _gate(name, status, reason, *evidence)
        normalized.append(gate.as_dict())

    status_by_name = {gate["name"]: gate["status"] for gate in normalized}
    all_pass = all(status_by_name[name] == "PASS" for name in REQUIRED_GATES)
    pit_pass = status_by_name["PIT"] == "PASS"
    qa_pass = status_by_name["INDEPENDENT_QA_RISK"] == "PASS"
    artifact: dict[str, Any] = {
        "artifact_type": "algo_trading_foundation_certification",
        "artifact_version": artifact_version,
        "generated_at": generated_at,
        "gates": normalized,
        "final_verdict": "PASS" if all_pass else (
            "BLOCKED" if any(status_by_name[name] == "BLOCKED" for name in REQUIRED_GATES) else "FAIL"
        ),
        "derived_flags": {
            "CAN_GENERATE_HYPOTHESES": all_pass,
            "CAN_DO_ENGINEERING_DIAGNOSTICS": all_pass,
            "CAN_RUN_NON_ECONOMIC_TESTS": all_pass,
            "CAN_RUN_DIAGNOSTIC_BACKTEST": all_pass,
            "CAN_RUN_CERTIFIED_BACKTEST": all_pass,
            "CAN_CLAIM_ECONOMIC_EVIDENCE": all_pass,
            "CAN_SUBMIT_QA": all_pass,
            "CAN_PROMOTE_TO_PAPER_CANDIDATE": all_pass and qa_pass,
            "CAN_RUN_FORWARD_PAPER": all_pass and pit_pass and qa_pass,
            "CAN_RUN_REAL_TIME_PAPER": all_pass and pit_pass and qa_pass,
            "CAN_MARK_LIVE_CANDIDATE": False,
            "CAN_DEPLOY_REAL_CAPITAL": False,
            "CAN_RESEARCH": all_pass,
            "CAN_BACKTEST_DIAGNOSTICALLY": all_pass,
        },
        "safety": {
            "live_trading": False,
            "capital_deployment": False,
            "unknown_is_pass": False,
            "current_constituents_used_as_historical_pit": False,
        },
    }
    canonical = json.dumps(artifact, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    artifact["artifact_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return artifact


def verify_foundation_artifact_integrity(artifact: Mapping[str, Any]) -> str:
    """Verify artifact checksum against canonical serialization. Returns computed SHA-256."""
    if not isinstance(artifact, Mapping):
        raise PermissionError("Certification artifact must be a mapping/dict")
    stored_hash = artifact.get("artifact_sha256")
    if not stored_hash:
        raise PermissionError("Foundation certification artifact missing 'artifact_sha256'")
    payload = {k: v for k, v in artifact.items() if k != "artifact_sha256"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    computed_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if computed_hash != stored_hash:
        raise PermissionError(
            f"Foundation certification checksum mismatch: stored={stored_hash}, computed={computed_hash}"
        )
    return computed_hash


def require_realtime_paper_certification(path: str | Path) -> dict[str, Any]:
    """Fail closed before a paper session can be started. Verifies file, SHA-256 and PASS status."""

    artifact_path = Path(path)
    if not artifact_path.is_file():
        raise PermissionError("Foundation certification artifact is missing")
    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PermissionError("Foundation certification artifact is unreadable") from exc

    verify_foundation_artifact_integrity(artifact)

    flags = artifact.get("derived_flags")
    if not isinstance(flags, Mapping) or flags.get("CAN_RUN_REAL_TIME_PAPER") is not True:
        raise PermissionError("Foundation certification does not authorize real-time paper")
    if artifact.get("final_verdict") != "PASS":
        raise PermissionError("Foundation certification verdict is not PASS")
    return artifact


class FoundationCertificationRegistry:
    """Authoritative registry for persisting and resolving foundation certifications in DuckDB."""

    @classmethod
    def register_artifact(
        cls,
        conn: Any,
        artifact: Mapping[str, Any],
        certification_id: str | None = None,
        is_active: bool = True,
        code_sha: str = "HEAD",
        pit_certification_id: str | None = None,
        pit_hash: str | None = None,
        cost_policy_id: str | None = None,
        cost_policy_hash: str | None = None,
        risk_policy_id: str | None = None,
        risk_policy_hash: str | None = None,
        robustness_policy_id: str | None = None,
        qa_review_id: str | None = None,
        supersedes_id: str | None = None,
    ) -> str:
        """Register a foundation certification artifact into DuckDB table foundation_certifications."""
        computed_sha = verify_foundation_artifact_integrity(artifact)
        cid = certification_id or str(artifact.get("artifact_id", "")) or f"cert_{computed_sha[:16]}"
        raw_conn = getattr(conn, "conn", conn)

        gates = artifact.get("gates", [])
        status = str(artifact.get("final_verdict", "BLOCKED"))
        lineage_status = "UNKNOWN"
        for g in gates:
            if isinstance(g, dict) and g.get("name") == "LINEAGE":
                lineage_status = str(g.get("status", "BLOCKED"))

        flags = artifact.get("derived_flags", {})
        if not isinstance(flags, Mapping):
            flags = {}

        if is_active:
            raw_conn.execute("UPDATE foundation_certifications SET is_active = FALSE WHERE is_active = TRUE")

        query = """
            INSERT OR REPLACE INTO foundation_certifications (
                foundation_certification_id, artifact_version, generated_at, status,
                code_sha, pit_certification_id, pit_hash, lineage_status,
                cost_policy_id, cost_policy_hash, risk_policy_id, risk_policy_hash,
                robustness_policy_id, qa_review_id, gates_json, derived_flags_json,
                artifact_sha256, artifact_json, supersedes_id, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        raw_conn.execute(
            query,
            [
                cid,
                str(artifact.get("artifact_version", "unknown")),
                str(artifact.get("generated_at")),
                status,
                code_sha,
                pit_certification_id,
                pit_hash,
                lineage_status,
                cost_policy_id,
                cost_policy_hash,
                risk_policy_id,
                risk_policy_hash,
                robustness_policy_id,
                qa_review_id,
                json.dumps(gates, sort_keys=True),
                json.dumps(flags, sort_keys=True),
                computed_sha,
                json.dumps(dict(artifact), sort_keys=True),
                supersedes_id,
                is_active,
            ],
        )
        return cid

    @classmethod
    def get_active_certification(cls, conn: Any) -> dict[str, Any] | None:
        """Load the active foundation certification from DuckDB, reconstructing the artifact dict."""
        raw_conn = getattr(conn, "conn", conn)
        try:
            row = raw_conn.execute(
                """SELECT artifact_json, artifact_sha256
                   FROM foundation_certifications
                   WHERE is_active = TRUE
                   ORDER BY recorded_at DESC LIMIT 1"""
            ).fetchone()
        except Exception:
            return None
        if not row:
            return None
        artifact = json.loads(row[0])
        verify_foundation_artifact_integrity(artifact)
        return artifact

    @classmethod
    def require_active_certification(cls, conn: Any) -> dict[str, Any]:
        """Load and fail-closed verify active foundation certification from DuckDB."""
        cert = cls.get_active_certification(conn)
        if cert is None:
            raise PermissionError("No active foundation certification found in registry.")
        flags = cert.get("derived_flags", {})
        if not isinstance(flags, Mapping) or flags.get("CAN_RUN_REAL_TIME_PAPER") is not True:
            raise PermissionError("Active foundation certification does not authorize paper trading.")
        if cert.get("final_verdict") != "PASS":
            raise PermissionError(f"Active foundation certification verdict is '{cert.get('final_verdict')}', not PASS.")
        return cert


