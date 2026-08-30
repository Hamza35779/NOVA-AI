"""Tests for the Persona & System Prompt REST API."""

import pytest
from fastapi.testclient import TestClient

from nova_ai.server.app import create_app


@pytest.fixture
def test_app():
    # Setup - use a dummy engine for app creation
    app = create_app(engine=None, model="test-model")
    return app

@pytest.fixture
def client(test_app):
    return TestClient(test_app)

def test_list_personas(client):
    response = client.get("/api/personas")
    assert response.status_code == 200
    data = response.json()
    assert "personas" in data
    assert "active_id" in data
    assert data["active_id"] is not None
    assert len(data["personas"]) >= 5
    # check default is preset
    default_preset = next((p for p in data["personas"] if p["id"] == "preset_default"), None)
    assert default_preset is not None
    assert default_preset["is_preset"] is True

def test_create_custom_persona(client):
    payload = {
        "name": "Custom Tester",
        "description": "A test persona.",
        "system_prompt": "You are a tester.",
        "avatar": "🧪",
        "temperature": 0.5
    }
    response = client.post("/api/personas", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Custom Tester"
    assert data["is_preset"] is False
    assert data["id"] is not None

def test_update_persona(client):
    # First create
    payload = {
        "name": "To Update",
        "description": "To be updated.",
        "system_prompt": "Test.",
        "avatar": "🧪"
    }
    create_res = client.post("/api/personas", json=payload)
    persona_id = create_res.json()["id"]

    # Now update
    update_payload = {
        "name": "Updated Name",
        "temperature": 0.9
    }
    update_res = client.put(f"/api/personas/{persona_id}", json=update_payload)
    assert update_res.status_code == 200
    updated_data = update_res.json()
    assert updated_data["name"] == "Updated Name"
    assert updated_data["temperature"] == 0.9

def test_update_preset_fails(client):
    update_res = client.put("/api/personas/preset_default", json={"name": "Hacked"})
    assert update_res.status_code == 400

def test_delete_persona(client):
    # Create
    payload = {
        "name": "To Delete",
        "description": "Test delete.",
        "system_prompt": "Delete me."
    }
    create_res = client.post("/api/personas", json=payload)
    persona_id = create_res.json()["id"]

    # Delete
    del_res = client.delete(f"/api/personas/{persona_id}")
    assert del_res.status_code == 200

    # Ensure not found
    del_again = client.delete(f"/api/personas/{persona_id}")
    assert del_again.status_code == 404

def test_delete_preset_fails(client):
    del_res = client.delete("/api/personas/preset_default")
    assert del_res.status_code == 400

def test_set_active_persona(client):
    payload = {
        "name": "Active Test",
        "description": "Test active.",
        "system_prompt": "Active."
    }
    create_res = client.post("/api/personas", json=payload)
    persona_id = create_res.json()["id"]

    res = client.post(f"/api/personas/active/{persona_id}")
    assert res.status_code == 200
    assert res.json()["active_id"] == persona_id

    # Verify active id in list
    list_res = client.get("/api/personas")
    assert list_res.json()["active_id"] == persona_id
