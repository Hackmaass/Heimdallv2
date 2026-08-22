"""
Unit Tests for FastAPI REST Endpoints
"""

import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_api_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert "compute" in data


def test_api_tracks():
    res = client.get("/api/tracks")
    assert res.status_code == 200
    data = res.json()
    assert "tracks" in data
    assert "total" in data


def test_api_telemetry():
    res = client.get("/api/telemetry")
    assert res.status_code == 200
    data = res.json()
    assert "position" in data
    assert "battery_pct" in data


def test_api_flytbase_status():
    res = client.get("/api/flytbase/status")
    assert res.status_code == 200
    data = res.json()
    assert "vehicle_state" in data
    assert "mode" in data
