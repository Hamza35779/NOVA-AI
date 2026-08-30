import pytest
from fastapi.testclient import TestClient
from nova_ai.server.calendar_router import router
from fastapi import FastAPI
from unittest.mock import patch

app = FastAPI()
app.include_router(router)

client = TestClient(app)

@pytest.fixture
def mock_creds():
    with patch("nova_ai.server.calendar_router._load_creds", return_value={"provider": "caldav", "username": "testuser", "url": "http://test"}):
        yield

@pytest.fixture
def mock_empty_creds():
    with patch("nova_ai.server.calendar_router._load_creds", return_value={}):
        yield

def test_calendar_status_configured(mock_creds):
    response = client.get("/api/calendar/status")
    assert response.status_code == 200
    assert response.json() == {"configured": True, "provider": "caldav", "username": "testuser"}

def test_calendar_status_unconfigured(mock_empty_creds):
    response = client.get("/api/calendar/status")
    assert response.status_code == 200
    assert response.json() == {"configured": False}

@patch("nova_ai.server.calendar_router._save_creds")
def test_connect_calendar(mock_save):
    response = client.post("/api/calendar/connect", json={"provider": "caldav", "url": "http://test", "username": "testuser", "password": "password"})
    assert response.status_code == 200
    assert response.json() == {"status": "connected", "provider": "caldav"}
    mock_save.assert_called_once()

@patch("nova_ai.connectors.caldav_connector.CalDavConnector.fetch_events", return_value=[{"summary": "Test Event", "start": "2026-08-30 10:00"}])
def test_get_events(mock_fetch, mock_creds):
    response = client.get("/api/calendar/events")
    assert response.status_code == 200
    assert response.json() == {"events": [{"summary": "Test Event", "start": "2026-08-30 10:00"}], "total": 1}

@patch("nova_ai.connectors.caldav_connector.CalDavConnector.fetch_events", return_value=[{"summary": "Test Event", "start": "2026-08-30 10:00"}])
def test_get_agenda(mock_fetch, mock_creds):
    response = client.get("/api/calendar/agenda")
    assert response.status_code == 200
    assert "briefing" in response.json()
    assert response.json()["event_count"] == 1

def test_prep_meeting():
    response = client.post("/api/calendar/meeting-prep", json={"summary": "Sync"})
    assert response.status_code == 200
    assert "prep" in response.json()
    assert response.json()["summary"] == "Sync"

@patch("nova_ai.connectors.caldav_connector.CalDavConnector.create_event", return_value={"uid": "123", "summary": "Sync"})
def test_create_event(mock_create, mock_creds):
    response = client.post("/api/calendar/events", json={"summary": "Sync", "start": "2026-08-30 10:00", "end": "2026-08-30 11:00"})
    assert response.status_code == 200
    assert response.json() == {"uid": "123", "summary": "Sync"}
