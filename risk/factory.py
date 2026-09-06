from pathlib import Path
from typing import Any
import hashlib
import json
import yaml

from risk.engine import RiskEngine
from risk.models import CanonicalRiskPolicy, RiskPolicy


AUTHORITATIVE_RISK_FIELDS = frozenset({
    "max_position_pct",
    "max_gross_exposure_pct",
    "max_daily_loss_pct",
    "max_drawdown_pct",
    "max_sector_exposure_pct",
    "max_open_positions",
    "max_var_pct",
    "min_liquidity_crore",
})


def load_canonical_risk_policy(path: str | Path | None = None) -> CanonicalRiskPolicy:
    """Load and validate the authoritative risk policy from versioned YAML."""
    policy_path = Path(path) if path else Path(__file__).resolve().parents[1] / "config" / "risk_policy.yaml"
    if not policy_path.is_file():
        raise FileNotFoundError(f"Canonical risk policy file not found: {policy_path}")
    raw_content = policy_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw_content)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid risk policy file format in {policy_path}")

    limits = data.get("limits")
    if not isinstance(limits, dict):
        raise ValueError("Canonical risk policy must contain a 'limits' mapping")

    fields = set(limits)
    missing = sorted(AUTHORITATIVE_RISK_FIELDS - fields)
    unknown = sorted(fields - AUTHORITATIVE_RISK_FIELDS)
    if missing:
        raise ValueError(f"Canonical risk policy limits missing required fields: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"Canonical risk policy limits contain unknown fields: {', '.join(unknown)}")

    canonical_str = json.dumps(limits, sort_keys=True, separators=(",", ":"))
    computed_hash = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    governance = data.get("governance", {})
    allow_permissive = bool(governance.get("allow_permissive_defaults", False))

    return CanonicalRiskPolicy(
        policy_id=str(data.get("policy_id", "canonical-risk-policy-v1")),
        policy_version=str(data.get("policy_version", "1.0.0")),
        effective_from=str(data.get("effective_from", "2026-09-06")),
        policy_hash=computed_hash,
        allow_permissive_defaults=allow_permissive,
        **limits,
    )


def build_risk_policy(config: dict[str, Any]) -> RiskPolicy:
    """Build the runtime policy from the configured research risk section."""

    research = config.get("research")
    if not isinstance(research, dict):
        raise ValueError("Authoritative risk configuration requires a research mapping.")
    risk = research.get("risk")
    if not isinstance(risk, dict):
        raise ValueError("Authoritative risk configuration requires research.risk.")
    fields = set(risk)
    missing = sorted(AUTHORITATIVE_RISK_FIELDS - fields)
    unknown = sorted(fields - AUTHORITATIVE_RISK_FIELDS)
    if missing:
        raise ValueError(
            "Authoritative research.risk is missing required fields: "
            + ", ".join(missing)
        )
    if unknown:
        raise ValueError(
            "Authoritative research.risk contains unknown fields: "
            + ", ".join(unknown)
        )
    try:
        return RiskPolicy(**risk)
    except Exception as exc:
        raise ValueError(f"Invalid authoritative research.risk configuration: {exc}") from exc


def build_risk_engine(config: dict[str, Any] | None = None) -> RiskEngine:
    """Build an engine carrying the authoritative configured risk policy."""
    if config is not None:
        return RiskEngine(build_risk_policy(config))
    canonical = load_canonical_risk_policy()
    return RiskEngine(canonical.to_risk_policy())
