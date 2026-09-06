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
            "CAN_RESEARCH": all_pass,
            "CAN_BACKTEST_DIAGNOSTICALLY": all_pass,
            "CAN_PROMOTE_TO_PAPER_CANDIDATE": all_pass and qa_pass,
            "CAN_RUN_REAL_TIME_PAPER": all_pass and pit_pass and qa_pass,
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


def require_realtime_paper_certification(path: str | Path) -> dict[str, Any]:
    """Fail closed before a real-time paper session can be started."""

    artifact_path = Path(path)
    if not artifact_path.is_file():
        raise PermissionError("Foundation certification artifact is missing")
    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PermissionError("Foundation certification artifact is unreadable") from exc
    flags = artifact.get("derived_flags")
    if not isinstance(flags, Mapping) or flags.get("CAN_RUN_REAL_TIME_PAPER") is not True:
        raise PermissionError("Foundation certification does not authorize real-time paper")
    if artifact.get("final_verdict") != "PASS":
        raise PermissionError("Foundation certification verdict is not PASS")
    return artifact

