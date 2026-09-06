from __future__ import annotations

import math

import pytest

from trading_stack.kpi import (
    KPI_SCHEMA_VERSION,
    CanonicalKPIReport,
    KpiStatus,
    calculate_canonical_kpis,
)


def test_calculation_emits_versioned_gross_and_net_metric_contract() -> None:
    report = calculate_canonical_kpis(
        equity=[100.0, 102.0, 101.0, 104.0],
        gross_equity=[100.0, 103.0, 103.0, 107.0],
        period_returns=[0.02, -0.00980392156862745, 0.0297029702970297],
        frequency="daily",
        annualization_factor=252.0,
        trade_pnls=[2.0, -1.0],
        turnover_notional=[1000.0, 2000.0],
        gross_exposure=[0.20, 0.40, 0.30],
        costs={"fees": 1.0, "slippage": 2.0},
    )

    assert report.schema_version == KPI_SCHEMA_VERSION
    assert report.metrics["net.total_return"].value == pytest.approx(0.04)
    assert report.metrics["gross.total_return"].value == pytest.approx(0.07)
    assert report.metrics["net.sharpe"].annualization_factor == 252.0
    assert report.metrics["net.max_drawdown"].unit == "fraction"
    assert report.metrics["trades.count"].unit == "count"
    assert report.metrics["turnover.notional"].unit == "currency"
    assert report.metrics["exposure.gross_mean"].unit == "fraction"
    assert report.metrics["costs.total"].value == pytest.approx(3.0)


def test_missing_metric_is_null_with_explicit_status_not_zero() -> None:
    report = calculate_canonical_kpis(
        equity=[100.0, 101.0],
        period_returns=[0.01],
        frequency="daily",
        annualization_factor=252.0,
    )

    sharpe = report.metrics["net.sharpe"]
    assert sharpe.value is None
    assert sharpe.status is KpiStatus.UNAVAILABLE
    assert report.metrics["trades.count"].value is None


def test_serialization_round_trip_is_deterministic() -> None:
    report = calculate_canonical_kpis(
        equity=[100.0, 105.0],
        gross_equity=[100.0, 106.0],
        period_returns=[0.05],
        frequency="daily",
        annualization_factor=252.0,
    )

    encoded = report.to_dict()
    restored = CanonicalKPIReport.from_dict(encoded)
    assert restored == report
    assert report.to_json() == restored.to_json()
    assert math.isfinite(report.metrics["net.cagr"].value)
