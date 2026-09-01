"""Composition-root construction for the authoritative runtime risk policy."""

from __future__ import annotations

from typing import Any

from risk.engine import RiskEngine
from risk.models import RiskPolicy


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


def build_risk_engine(config: dict[str, Any]) -> RiskEngine:
    """Build an engine carrying the authoritative configured risk policy."""

    return RiskEngine(build_risk_policy(config))
