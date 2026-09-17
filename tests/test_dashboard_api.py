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


def test_dashboard_api_zero_loss_profit_factor_and_scoped_stats(client, monkeypatch, tmp_path):
    """Verifies None/null profit_factor for zero-loss runs and scoped stats under filter."""
    import duckdb
    from tools.dashboard.api import main as api_main

    db_path = tmp_path / "dash_stats_test.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE strategy_runs (
            run_id VARCHAR PRIMARY KEY,
            strategy_name VARCHAR,
            starting_capital DOUBLE,
            status VARCHAR
        );
        CREATE TABLE strategy_metrics (
            run_id VARCHAR,
            metric_name VARCHAR,
            metric_value DOUBLE
        );
        CREATE TABLE trade_round_trips (
            trade_id VARCHAR PRIMARY KEY,
            run_id VARCHAR,
            symbol VARCHAR,
            exit_timestamp TIMESTAMPTZ,
            net_pnl DOUBLE
        );
    """)
    conn.execute("INSERT INTO strategy_runs VALUES ('RUN_PERFECT', 'test_strat', 100000.0, 'COMPLETED');")
    conn.execute("INSERT INTO strategy_metrics VALUES ('RUN_PERFECT', 'max_drawdown', 0.25);")
    conn.execute("INSERT INTO strategy_metrics VALUES ('RUN_PERFECT', 'total_return', 0.15);")
    # All winning trades (zero losses)
    conn.execute("INSERT INTO trade_round_trips VALUES ('T1', 'RUN_PERFECT', 'INFY', '2026-01-10 15:30:00+05:30', 5000.0);")
    conn.execute("INSERT INTO trade_round_trips VALUES ('T2', 'RUN_PERFECT', 'TCS', '2026-01-15 15:30:00+05:30', 10000.0);")
    conn.close()

    monkeypatch.setattr(api_main, "DB_PATH", db_path)

    # 1. Unfiltered full-run: profit_factor must be None (null), max_drawdown from full-run metric (0.25)
    resp = client.get("/api/runs/RUN_PERFECT/analytics/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["profit_factor"] is None
    assert data["winning_trades"] == 2
    assert data["losing_trades"] == 0
    assert data["max_drawdown"] == pytest.approx(0.25)

    # 2. Filtered by symbol=INFY: max_drawdown should be scoped to INFY (0.0 since only 1 win)
    resp_scoped = client.get("/api/runs/RUN_PERFECT/analytics/stats?symbol=INFY")
    assert resp_scoped.status_code == 200
    scoped_data = resp_scoped.json()
    assert scoped_data["total_trades"] == 1
    assert scoped_data["base_investment_profit"] == pytest.approx(5000.0)
    assert scoped_data["max_drawdown"] == pytest.approx(0.0)


def test_dashboard_api_monthly_boundary_compounding(client, monkeypatch, tmp_path):
    """Verifies that monthly returns compound across month boundaries rather than losing overnight jumps."""
    import duckdb
    from tools.dashboard.api import main as api_main

    db_path = tmp_path / "dash_monthly_test.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE strategy_runs (
            run_id VARCHAR PRIMARY KEY,
            strategy_name VARCHAR,
            starting_capital DOUBLE,
            status VARCHAR
        );
        CREATE TABLE strategy_equity_curve (
            run_id VARCHAR,
            timestamp TIMESTAMPTZ,
            equity DOUBLE
        );
    """)
    # Starting capital: 100,000
    # Month 1 (Jan): starts 100k, ends Jan 31 at 110k (10% return)
    # Overnight Jan 31 -> Feb 1 jumps to 115k, ends Feb 28 at 121k
    # Feb return should be 121k / 110k - 1 = 10%, NOT 121k / 115k - 1 = 5.2%
    conn.execute("INSERT INTO strategy_runs VALUES ('RUN_MONTHLY', 'test', 100000.0, 'COMPLETED');")
    conn.execute("INSERT INTO strategy_equity_curve VALUES ('RUN_MONTHLY', '2026-01-02 15:30:00+05:30', 100000.0);")
    conn.execute("INSERT INTO strategy_equity_curve VALUES ('RUN_MONTHLY', '2026-01-31 15:30:00+05:30', 110000.0);")
    conn.execute("INSERT INTO strategy_equity_curve VALUES ('RUN_MONTHLY', '2026-02-01 09:15:00+05:30', 115000.0);")
    conn.execute("INSERT INTO strategy_equity_curve VALUES ('RUN_MONTHLY', '2026-02-28 15:30:00+05:30', 121000.0);")
    conn.close()

    monkeypatch.setattr(api_main, "DB_PATH", db_path)

    resp = client.get("/api/runs/RUN_MONTHLY/analytics/monthly")
    assert resp.status_code == 200
    res = resp.json()
    assert len(res) == 2
    # Jan: 110k / 100k - 1 = 0.10 (10%)
    assert res[0]["year"] == 2026 and res[0]["month"] == 1
    assert res[0]["return_pct"] == pytest.approx(0.10, rel=1e-3)
    # Feb: 121k / 110k - 1 = 0.10 (10%)
    assert res[1]["year"] == 2026 and res[1]["month"] == 2
    assert res[1]["return_pct"] == pytest.approx(0.10, rel=1e-3)
