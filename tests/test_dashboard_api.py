"""Integration tests for FastAPI dashboard endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tools.dashboard.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_dashboard_api_routes(client):
    """Test standard dashboard endpoints."""
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
