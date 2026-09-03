"""Shared causal portfolio economics used by authoritative execution paths."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from statistics import NormalDist
from typing import Any

import pandas as pd


CAMPAIGN_COST_POLICY_IDENTITY = "52e6a43699be4daee483c7503742b033235b0e47d918782ce74cf811aae8e79f"
_CAMPAIGN_FROZEN_COST_SCHEDULE_FINGERPRINTS = (
    ("angel-nse-delivery-2010-01", "2010-01-01", "6f4c1b3fbaab964004d87fad973d59d22a88b2d662eb47895f028488e45456ec"),
    ("angel-nse-delivery-2016-06", "2016-06-01", "fa4e0d50a01fecb358d8bbd142ae4418cf082d41efae3d3cd387e71173c7a0e2"),
    ("angel-nse-delivery-2024-10", "2024-10-01", "0f34303f0ee909f4cc72a5c5c51b717abbbf3c7586a8036e9ac160269c395304"),
    ("angel-nse-delivery-2026-04", "2026-04-01", "9e21abfdae92d5b9e6257a8d71e436865236c724b2ae05ab4005de2aaa37cb8f"),
)


def marked_to_market_equity(
    cash: float,
    quantities: Mapping[str, float],
    marks: Mapping[str, float],
) -> float:
    """Return cash plus holdings marked at prices known at the decision time."""

    return float(cash) + sum(
        float(quantity) * float(marks.get(symbol, 0.0))
        for symbol, quantity in quantities.items()
    )


def target_notional(target_weight: float, current_equity: float) -> float:
    """Convert a target weight into notional using current, not starting, equity."""

    return max(float(target_weight), 0.0) * max(float(current_equity), 0.0)


def max_affordable_quantity(
    requested_quantity: float,
    available_cash: float,
    cost_for_quantity: Callable[[int], tuple[float, float]],
) -> int:
    """Find the largest whole quantity whose execution total fits available cash.

    ``cost_for_quantity`` returns ``(execution_price, statutory_fees)`` for the
    candidate quantity, allowing participation-dependent costs to be recomputed
    for every binary-search candidate.
    """

    requested = max(int(math.floor(float(requested_quantity))), 0)
    cash = max(float(available_cash), 0.0)
    if requested == 0 or cash <= 0:
        return 0

    def fits(quantity: int) -> bool:
        price, fees = cost_for_quantity(quantity)
        total = quantity * float(price) + float(fees)
        return math.isfinite(total) and total <= cash + max(cash * 1e-12, 1e-9)

    if not fits(1):
        return 0
    if fits(requested):
        return requested

    low, high = 1, requested
    while low < high:
        midpoint = (low + high + 1) // 2
        if fits(midpoint):
            low = midpoint
        else:
            high = midpoint - 1
    return low


def economic_contract_hash(payload: Mapping[str, Any]) -> str:
    """Return a deterministic identity for a run's economic assumptions."""

    import hashlib
    import json

    encoded = json.dumps(dict(payload), sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def calculate_projected_var_pct(
    *,
    volatility: float | None,
    projected_gross: float,
    equity: float,
) -> float | None:
    """Calculate the shared causal one-day projected portfolio VaR input."""

    if volatility is None or not math.isfinite(float(volatility)) or float(volatility) <= 0:
        return None
    if not math.isfinite(float(projected_gross)) or projected_gross < 0:
        return None
    if not math.isfinite(float(equity)) or equity <= 0:
        return None
    return NormalDist().inv_cdf(0.95) * float(volatility) * float(projected_gross) / float(equity)


def causal_rolling_volatility(
    closes: pd.Series,
    *,
    window: int = 20,
    include_current: bool = False,
) -> pd.Series:
    """Return rolling close volatility using only prices available at evaluation."""

    returns = pd.to_numeric(closes, errors="coerce").pct_change()
    if not include_current:
        returns = returns.shift(1)
    return returns.rolling(window, min_periods=window).std(ddof=1)


def cost_schedule_identity(
    execution_dates: list[Any],
    resolver: Callable[[Any], Any],
) -> str:
    """Hash the effective cost schedule and date for every execution regime."""

    regimes: list[dict[str, Any]] = []
    previous: str | None = None
    for execution_date in sorted(set(execution_dates)):
        schedule = resolver(execution_date)
        schedule_hash = economic_contract_hash(dict(schedule.__dict__))
        if schedule_hash != previous:
            regimes.append({
                "effective_date": str(execution_date),
                "version": str(getattr(schedule, "version", "")),
                "schedule_hash": schedule_hash,
            })
            previous = schedule_hash
    return economic_contract_hash({"regimes": regimes})


def campaign_cost_policy_identity(schedules: Iterable[Any]) -> str:
    """Return the identity of an ordered, date-effective Campaign 1 cost policy."""

    schedules = tuple(schedules)
    policy = [
        {
            "effective_from": str(getattr(schedule, "effective_from", "")),
            "version": str(getattr(schedule, "version", "")),
            "schedule": dict(getattr(schedule, "__dict__", {})),
        }
        for schedule in schedules
    ]
    fingerprints = tuple(
        (
            str(getattr(schedule, "version", "")),
            str(getattr(schedule, "effective_from", "")),
            economic_contract_hash(dict(getattr(schedule, "__dict__", {}))),
        )
        for schedule in schedules
    )
    if fingerprints == _CAMPAIGN_FROZEN_COST_SCHEDULE_FINGERPRINTS:
        return CAMPAIGN_COST_POLICY_IDENTITY
    return economic_contract_hash({"ordered_effective_schedules": policy})
