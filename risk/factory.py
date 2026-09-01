"""Composition-root construction for the authoritative runtime risk policy."""

from __future__ import annotations

from typing import Any

from risk.engine import RiskEngine
from risk.models import RiskPolicy


def build_risk_policy(config: dict[str, Any]) -> RiskPolicy:
    """Build the runtime policy from the configured research risk section."""

    research = config.get("research")
    if not isinstance(research, dict):
        raise ValueError("Authoritative risk configuration requires a research mapping.")
    risk = research.get("risk")
    if not isinstance(risk, dict):
        raise ValueError("Authoritative risk configuration requires research.risk.")
    try:
        return RiskPolicy(**risk)
    except Exception as exc:
        raise ValueError(f"Invalid authoritative research.risk configuration: {exc}") from exc


def build_risk_engine(config: dict[str, Any]) -> RiskEngine:
    """Build an engine carrying the authoritative configured risk policy."""

    return RiskEngine(build_risk_policy(config))
