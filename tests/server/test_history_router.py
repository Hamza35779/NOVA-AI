"""Tests for the persistent conversation history API."""
from __future__ import annotations
import pytest
from fastapi.testclient import TestClient


class TestHistoryAPI:
    @pytest.fixture
    def client(self):
        try:
            from nova_ai.server.app import create_app
            app = create_app(engine=None, model="dummy")
            return TestClient(app)
        except ImportError:
            from nova_ai.server.main import app
            return TestClient(app)

    def test_list_empty(self, client):
        res = client.get("/api/history")
        assert res.status_code == 200
        assert "conversations" in res.json()

    def test_create_and_get(self, client):
        res = client.post("/api/history", json={"title": "Test Chat"})
        assert res.status_code == 200
        conv_id = res.json()["id"]

        detail = client.get(f"/api/history/{conv_id}")
        assert detail.status_code == 200
        assert detail.json()["title"] == "Test Chat"
        assert detail.json()["messages"] == []

    def test_add_message(self, client):
        conv = client.post("/api/history", json={"title": "Msg Test"}).json()
        conv_id = conv["id"]
        res = client.post(f"/api/history/{conv_id}/messages", json={"role": "user", "content": "Hello NOVA"})
        assert res.status_code == 200
        assert res.json()["role"] == "user"

    def test_pin_conversation(self, client):
        conv = client.post("/api/history", json={"title": "Pin Test"}).json()
        conv_id = conv["id"]
        res = client.put(f"/api/history/{conv_id}", json={"pinned": True})
        assert res.status_code == 200
        assert res.json()["pinned"] == 1

    def test_search(self, client):
        conv = client.post("/api/history", json={"title": "Search Test"}).json()
        conv_id = conv["id"]
        client.post(f"/api/history/{conv_id}/messages", json={"role": "user", "content": "quantum computing is fascinating"})
        res = client.get("/api/history/search?q=quantum")
        assert res.status_code == 200
        assert len(res.json()["results"]) >= 1

    def test_delete_conversation(self, client):
        conv = client.post("/api/history", json={"title": "Delete Test"}).json()
        conv_id = conv["id"]
        res = client.delete(f"/api/history/{conv_id}")
        assert res.status_code == 200
        gone = client.get(f"/api/history/{conv_id}")
        assert gone.status_code == 404

    def test_get_nonexistent(self, client):
        res = client.get("/api/history/does-not-exist")
        assert res.status_code == 404
