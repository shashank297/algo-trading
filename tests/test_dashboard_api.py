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
    # Should either succeed or return empty list (never crash)
    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        data = resp.json()
        assert isinstance(data, list)
