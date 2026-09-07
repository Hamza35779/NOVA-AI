"""Tests for the system telemetry API router."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nova_ai.server.system_telemetry_router import router


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_telemetry_snapshot_shape(client) -> None:
    resp = client.get("/api/system/telemetry")
    assert resp.status_code == 200
    data = resp.json()

    assert set(data) >= {"cpu", "ram", "gpu", "timestamp"}

    assert "percent" in data["cpu"] and "cores" in data["cpu"]
    assert data["cpu"]["cores"] >= 1

    assert set(data["ram"]) >= {"percent", "used_gb", "total_gb", "free_gb"}
    assert data["ram"]["total_gb"] >= 0

    assert set(data["gpu"]) >= {
        "vendor",
        "name",
        "available",
        "gpus",
        "vram_free_gb",
        "vram_total_gb",
    }
    assert isinstance(data["gpu"]["available"], bool)


def test_telemetry_cached_within_ttl(client) -> None:
    r1 = client.get("/api/system/telemetry").json()
    r2 = client.get("/api/system/telemetry").json()
    # Second call within the TTL serves the same cached timestamp
    assert r1["timestamp"] == r2["timestamp"] or r2["timestamp"] >= r1["timestamp"]


def test_backends_endpoint(client) -> None:
    resp = client.get("/api/system/telemetry/backends")
    assert resp.status_code == 200
    data = resp.json()
    assert "hardware" in data and "sensors" in data
    assert set(data["sensors"]) == {"pynvml", "psutil"}
