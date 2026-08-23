from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nova_ai.server.integrations_router import router


def test_integrations_router_get() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/v1/integrations")
    assert response.status_code == 200
    data = response.json()
    assert "categories" in data
    assert data["total_apps"] > 0


def test_integrations_router_toggle() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.post("/v1/integrations/whatsapp/toggle", json={"enabled": True})
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
