"""Integration tests for FastAPI dashboard endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tools.dashboard.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_dashboard_api_routes(client, monkeypatch, tmp_path):
    """Test standard dashboard endpoints."""
    import duckdb
    from tools.dashboard.api import main as api_main

    # These endpoints require a real DuckDB file with the dashboard schema present;
    # point DB_PATH at a fresh, empty-but-schema-valid database for this test instead
    # of depending on a market_data.duckdb that may not exist in a clean checkout/CI run.
    db_path = tmp_path / "dashboard_routes_test.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE strategy_runs (
            run_id VARCHAR PRIMARY KEY,
            strategy_name VARCHAR,
            symbol VARCHAR,
            mode VARCHAR,
            started_at TIMESTAMPTZ,
            status VARCHAR,
            starting_capital DOUBLE
        );
        CREATE TABLE strategy_metrics (
            run_id VARCHAR,
            metric_name VARCHAR,
            metric_value DOUBLE
        );
    """)
    conn.close()
    monkeypatch.setattr(api_main, "DB_PATH", db_path)

    # Test runs endpoint
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)

    # Test strategies endpoint
    strat_resp = client.get("/api/strategies")
    assert strat_resp.status_code == 200
    strat_data = strat_resp.json()
    assert isinstance(strat_data, list)

    # Test nonexistent run returns 404 or empty data without 500 server crash
    trade_resp = client.get("/api/trades?run_id=nonexistent_test_run_123")
    assert trade_resp.status_code in (200, 404)


def test_dashboard_api_dynamic_starting_capital(client, monkeypatch, tmp_path):
    """E-4 & P1-20: Verifies that monthly analytics uses dynamic starting_capital from strategy_runs."""
    import duckdb
    from tools.dashboard.api import main as api_main

    db_path = tmp_path / "dash_test.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE strategy_runs (
            run_id VARCHAR PRIMARY KEY,
            strategy_name VARCHAR,
            starting_capital DOUBLE,
            status VARCHAR
        );
        CREATE TABLE trade_round_trips (
            trade_id VARCHAR PRIMARY KEY,
            run_id VARCHAR,
            symbol VARCHAR,
            exit_timestamp TIMESTAMPTZ,
            net_pnl DOUBLE
        );
        CREATE TABLE strategy_equity_curve (
            run_id VARCHAR,
            timestamp TIMESTAMPTZ,
            equity DOUBLE
        );
    """)
    # Run with 500,000 capital and 50,000 profit (10% return)
    conn.execute("INSERT INTO strategy_runs VALUES ('RUN_500K', 'momentum', 500000.0, 'COMPLETED');")
    conn.execute("INSERT INTO trade_round_trips VALUES ('T1', 'RUN_500K', 'RELIANCE', '2026-03-15 15:30:00+05:30', 50000.0);")
    conn.close()

    monkeypatch.setattr(api_main, "DB_PATH", db_path)

    resp = client.get("/api/runs/RUN_500K/analytics/monthly?symbol=RELIANCE")
    assert resp.status_code == 200
    res = resp.json()
    assert len(res) == 1
    # 50,000 / 500,000 = 0.10 (10%), NOT 50,000 / 100,000 = 0.50 (50%)
    assert res[0]["return_pct"] == pytest.approx(0.10, rel=1e-3)


def test_dashboard_api_missing_db_handling(client, monkeypatch, tmp_path):
    """E-4: Verifies clean 500 error when DB file is missing."""
    from tools.dashboard.api import main as api_main
    monkeypatch.setattr(api_main, "DB_PATH", tmp_path / "non_existent.duckdb")

    resp = client.get("/api/runs/test_missing_db_123/equity-curve")
    assert resp.status_code == 500
    assert "Database file not found" in resp.json()["detail"]
