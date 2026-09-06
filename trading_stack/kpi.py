"""Versioned, provider-neutral KPI contract for research and paper reports."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable


KPI_SCHEMA_VERSION = "1.0.0"


class KpiStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class KpiMetric:
    value: float | int | None
    unit: str
    window: str
    annualization_factor: float | None
    status: KpiStatus
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "window": self.window,
            "annualization_factor": self.annualization_factor,
            "status": self.status.value,
            "basis": self.basis,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "KpiMetric":
        return cls(
            value=value.get("value"),
            unit=str(value["unit"]),
            window=str(value["window"]),
            annualization_factor=value.get("annualization_factor"),
            status=KpiStatus(value["status"]),
            basis=str(value["basis"]),
        )


@dataclass(frozen=True, slots=True)
class CanonicalKPIReport:
    schema_version: str
    frequency: str
    observation_count: int
    metrics: dict[str, KpiMetric]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "frequency": self.frequency,
            "observation_count": self.observation_count,
            "metrics": {name: self.metrics[name].to_dict() for name in sorted(self.metrics)},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CanonicalKPIReport":
        return cls(
            schema_version=str(value["schema_version"]),
            frequency=str(value["frequency"]),
            observation_count=int(value["observation_count"]),
            metrics={name: KpiMetric.from_dict(metric) for name, metric in value["metrics"].items()},
        )


def _metric(value: float | int | None, *, unit: str, annualization_factor: float | None, basis: str, frequency: str) -> KpiMetric:
    return KpiMetric(
        value=value,
        unit=unit,
        window="full_sample",
        annualization_factor=annualization_factor,
        status=KpiStatus.AVAILABLE if value is not None else KpiStatus.UNAVAILABLE,
        basis=basis,
    )


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _std(values: list[float]) -> float | None:
    if not values:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _return_metrics(equity: list[float], returns: list[float], factor: float) -> dict[str, float | None]:
    total = equity[-1] / equity[0] - 1.0 if len(equity) >= 2 and equity[0] > 0 else None
    years = len(returns) / factor if factor > 0 else 0.0
    cagr = (equity[-1] / equity[0]) ** (1.0 / years) - 1.0 if total is not None and equity[-1] > 0 and years > 0 else None
    volatility = _std(returns)
    annualized_volatility = volatility * math.sqrt(factor) if volatility is not None else None
    sharpe = (sum(returns) / len(returns) / volatility) * math.sqrt(factor) if volatility and returns else None
    downside = [value for value in returns if value < 0]
    downside_std = _std(downside)
    sortino = (sum(returns) / len(returns) / downside_std) * math.sqrt(factor) if downside_std and returns else None
    peak = equity[0] if equity else None
    drawdowns: list[float] = []
    for value in equity:
        peak = max(peak, value) if peak is not None else value
        drawdowns.append(value / peak - 1.0)
    return {
        "total_return": total,
        "cagr": cagr,
        "volatility": annualized_volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": min(drawdowns) if drawdowns else None,
    }


def _equity_returns(equity: list[float]) -> list[float]:
    return [equity[index] / equity[index - 1] - 1.0 for index in range(1, len(equity))]


def calculate_canonical_kpis(
    *,
    equity: Iterable[float],
    period_returns: Iterable[float],
    frequency: str,
    annualization_factor: float,
    gross_equity: Iterable[float] | None = None,
    trade_pnls: Iterable[float] | None = None,
    turnover_notional: Iterable[float] | None = None,
    gross_exposure: Iterable[float] | None = None,
    costs: dict[str, float] | None = None,
) -> CanonicalKPIReport:
    """Calculate deterministic full-sample KPIs from causal period-level inputs.

    Returns are decimal fractions, costs/turnover are currency units, exposure is a
    fraction of equity, and unavailable inputs remain null rather than becoming zero.
    """
    equity_values = [float(value) for value in equity]
    returns = [float(value) for value in period_returns]
    if len(equity_values) < 2:
        raise ValueError("equity must contain at least two observations")
    if annualization_factor <= 0:
        raise ValueError("annualization_factor must be positive")
    net = _return_metrics(equity_values, returns, annualization_factor)
    metrics: dict[str, KpiMetric] = {}
    for name, value in net.items():
        metrics[f"net.{name}"] = _metric(value, unit="fraction", annualization_factor=annualization_factor, basis="net_period_returns", frequency=frequency)
    if gross_equity is not None:
        gross_values = [float(v) for v in gross_equity]
        for name, value in _return_metrics(gross_values, _equity_returns(gross_values), annualization_factor).items():
            metrics[f"gross.{name}"] = _metric(value, unit="fraction", annualization_factor=annualization_factor, basis="gross_equity_curve", frequency=frequency)
    else:
        for name in ("total_return", "cagr", "volatility", "sharpe", "sortino", "max_drawdown"):
            metrics[f"gross.{name}"] = _metric(None, unit="fraction", annualization_factor=annualization_factor, basis="gross_equity_curve_required", frequency=frequency)

    trades = [float(value) for value in trade_pnls] if trade_pnls is not None else None
    metrics["trades.count"] = _metric(len(trades) if trades is not None else None, unit="count", annualization_factor=None, basis="completed_trade_pnls", frequency=frequency)
    metrics["trades.hit_rate"] = _metric(sum(value > 0 for value in trades) / len(trades) if trades else None, unit="fraction", annualization_factor=None, basis="completed_trade_pnls", frequency=frequency)
    turnover = [float(value) for value in turnover_notional] if turnover_notional is not None else None
    metrics["turnover.notional"] = _metric(sum(turnover) if turnover is not None else None, unit="currency", annualization_factor=None, basis="filled_notional", frequency=frequency)
    exposure = [float(value) for value in gross_exposure] if gross_exposure is not None else None
    metrics["exposure.gross_mean"] = _metric(sum(exposure) / len(exposure) if exposure else None, unit="fraction", annualization_factor=None, basis="gross_exposure_over_equity", frequency=frequency)
    cost_values = costs or {}
    metrics["costs.total"] = _metric(sum(float(value) for value in cost_values.values()) if costs is not None else None, unit="currency", annualization_factor=None, basis="fees_plus_slippage_plus_explicit_costs", frequency=frequency)
    metrics["capacity.max_participation"] = _metric(None, unit="fraction", annualization_factor=None, basis="requires_participation_limit_and_volume", frequency=frequency)
    metrics["liquidity.median_daily_value"] = _metric(None, unit="currency", annualization_factor=None, basis="requires_point_in_time_volume", frequency=frequency)
    metrics["uncertainty.return_ci_95"] = _metric(None, unit="fraction", annualization_factor=None, basis="requires_declared_resampling_method", frequency=frequency)
    return CanonicalKPIReport(KPI_SCHEMA_VERSION, frequency, len(returns), metrics)
