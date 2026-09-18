"""Focused regressions for the remaining platform-remediation defects."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pytest
import json

from clean_db import main as clean_db_main
from data_platform.contracts import BarRequest, PriceAdjustment
from data_platform.providers import ProviderRegistry, ProviderUnavailable
from tools.dashboard.api import main as dashboard_api
from tools.nifty200_pit.instrument_resolver import (
    resolve_observation,
    validate_alias_intervals,
)
from tools.nifty200_pit.models import Observation
from ai_research.workflow import ResearchWorkflow
from storage.duckdb_manager import DuckDBManager
from storage.migrations.runner import MigrationRunner


class _Provider:
    def __init__(self, name: str, error: ProviderUnavailable | None = None) -> None:
        self.name = name
        self.error = error
        self.calls = 0

    def fetch_bars(self, request: BarRequest):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return "snapshot"


def _request() -> BarRequest:
    return BarRequest(
        symbol="RELIANCE",
        exchange="NSE",
        timeframe="1d",
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 2, tzinfo=timezone.utc),
        adjustment=PriceAdjustment.UNADJUSTED,
    )


def test_provider_registry_falls_back_only_for_availability() -> None:
    unavailable = _Provider("first", ProviderUnavailable("timeout", category="TRANSIENT"))
    second = _Provider("second")
    assert ProviderRegistry([unavailable, second]).fetch_bars(_request()) == "snapshot"
    assert unavailable.calls == 1
    assert second.calls == 1

    auth = _Provider("auth", ProviderUnavailable("bad key", category="AUTH"))
    backup = _Provider("backup")
    with pytest.raises(ProviderUnavailable, match="bad key"):
        ProviderRegistry([auth, backup]).fetch_bars(_request())
    assert backup.calls == 0


def test_alias_validation_rejects_cross_instrument_overlap_and_bad_identity() -> None:
    base = {
        "exchange": "NSE",
        "alias_symbol": "OLD",
        "confidence": "CERTIFIED",
        "resolution_status": "ACCEPTED",
    }
    aliases = [
        base | {"alias_id": "a", "instrument_id": "SEC-1", "valid_from": date(2020, 1, 1), "valid_until": date(2022, 1, 1)},
        base | {"alias_id": "b", "instrument_id": "SEC-2", "valid_from": date(2021, 1, 1), "valid_until": date(2023, 1, 1)},
        base | {"alias_id": "c", "instrument_id": "None", "valid_from": date(2020, 1, 1)},
    ]
    errors = validate_alias_intervals(aliases)
    assert "alias_interval_overlap:NSE:OLD" in errors
    assert "invalid_alias_identity:c" in errors


def test_identity_resolution_does_not_persist_sentinel_isin() -> None:
    observation = Observation(symbol="OLD", isin="None", effective_date=date(2021, 1, 1))
    resolution = resolve_observation(
        observation,
        [{"instrument_id": "SEC-1", "symbol": "OLD", "isin": "nan"}],
    )
    assert resolution.instrument_id == "SEC-1"
    assert resolution.isin is None


def test_clean_db_requires_explicit_target_permission(tmp_path: Path) -> None:
    database = tmp_path / "research.duckdb"
    conn = duckdb.connect(str(database))
    conn.execute("CREATE TABLE strategy_runs (run_id VARCHAR)")
    conn.close()
    assert clean_db_main(["--database", str(database), "--dry-run"]) == 2
    assert clean_db_main(["--database", str(database), "--permit-target", "--dry-run"]) == 0


def test_dashboard_profit_factor_is_json_safe(monkeypatch, tmp_path: Path) -> None:
    database = tmp_path / "dashboard.duckdb"
    conn = duckdb.connect(str(database))
    conn.execute("CREATE TABLE trade_round_trips (run_id VARCHAR, symbol VARCHAR, exit_timestamp TIMESTAMPTZ, net_pnl DOUBLE)")
    conn.execute("CREATE TABLE strategy_metrics (run_id VARCHAR, metric_name VARCHAR, metric_value DOUBLE)")
    conn.execute("CREATE TABLE strategy_runs (run_id VARCHAR, starting_capital DOUBLE)")
    conn.execute("INSERT INTO strategy_runs VALUES ('R', 100000)")
    conn.execute("INSERT INTO trade_round_trips VALUES ('R', 'ABC', '2024-01-02 10:00:00+00:00', 100.0)")
    conn.close()
    monkeypatch.setattr(dashboard_api, "DB_PATH", database)
    result = dashboard_api.get_analytics_stats("R", symbol=None, year=None)
    assert result.profit_factor == "INFINITE"
    assert result.model_dump(mode="json")["profit_factor"] == "INFINITE"


def test_ai_risk_market_rows_require_certification_and_availability(tmp_path: Path) -> None:
    database = tmp_path / "risk.duckdb"
    MigrationRunner(str(database)).run_migrations()
    db = DuckDBManager(str(database))
    try:
        content_hash = "raw-risk-hash"
        db.conn.execute(
            """INSERT INTO market_datasets
               (dataset_id, symbol, canonical_symbol, exchange, timeframe, provider_name,
                adjustment, lifecycle_status, status, raw_hash, transformation_hash)
               VALUES ('DS-RISK', 'ABC', 'ABC', 'NSE', '1d', 'test', 'UNADJUSTED',
                       'CANONICAL_PROMOTED', 'VERIFIED', ?, NULL)""",
            [content_hash],
        )
        db.record_market_dataset_availability("DS-RISK", "2024-01-01T00:00:00+00:00")
        certification_time = "2024-01-01T00:00:00+00:00"
        db.conn.execute(
            """INSERT INTO data_quality_certifications
               (certification_id, dataset_id, validator_version, check_count, issue_count,
                checks_json, status, started_at, completed_at)
               VALUES ('CERT-RISK', 'DS-RISK', 'test', 6, 0, ?, 'CERTIFIED', ?, ?)""",
            [json.dumps({"dataset_content_hash": content_hash}), certification_time, certification_time],
        )
        for index, check_type in enumerate((
            "schema", "ohlc_integrity", "duplicates", "session_alignment", "missing_sessions", "timestamp_integrity",
        )):
            db.conn.execute(
                """INSERT INTO quality_report
                   (id, symbol, timeframe, dataset_id, check_type, issue_count, details, certification_id)
                   VALUES (?, 'ABC', '1d', 'DS-RISK', ?, 0, '{}', 'CERT-RISK')""",
                [index + 1, check_type],
            )
        for index in range(21):
            timestamp = f"2024-01-{index + 1:02d} 10:00:00+00:00"
            db.conn.execute(
                """INSERT INTO historical_candles
                   (symbol, token, exchange, timeframe, timestamp, open, high, low, close,
                    volume, adjustment, provider_name, dataset_id)
                   VALUES ('ABC', '1', 'NSE', '1d', ?, 10, 11, 9, ?, 1000,
                           'UNADJUSTED', 'test', 'DS-RISK')""",
                [timestamp, 10 + index],
            )
            db.record_historical_candle_availability(
                "DS-RISK", "ABC", "NSE", "1d", timestamp, "2024-01-01T00:00:00+00:00",
            )
        workflow = ResearchWorkflow(db, object())
        rows = workflow._authoritative_market_rows(
            {"ABC"}, "1d", "UNADJUSTED", "2024-01-30T00:00:00+00:00", minimum_rows=21,
        )
        assert rows is not None
        assert len(rows["ABC"]) == 21

        db.conn.execute("UPDATE market_datasets SET status = 'VALID' WHERE dataset_id = 'DS-RISK'")
        assert workflow._authoritative_market_rows(
            {"ABC"}, "1d", "UNADJUSTED", "2024-01-30T00:00:00+00:00", minimum_rows=1,
        ) is None
    finally:
        db.close()
