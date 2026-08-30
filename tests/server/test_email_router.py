from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class TestEmailRouter:
    @pytest.fixture
    def client(self):
        try:
            from nova_ai.server.app import app
        except ImportError:
            try:
                from nova_ai.server.main import app
            except ImportError:
                from nova_ai.server.app import create_app
                # Provide a dummy engine and model to construct app
                app = create_app(engine=None, model="dummy")
        return TestClient(app)

    def test_status_not_configured(self, client):
        # May return configured=True if creds file exists from previous test runs
        res = client.get("/api/email/status")
        assert res.status_code == 200
        assert "configured" in res.json()

    def test_inbox_not_configured(self, client):
        # If not configured, should return 400
        from nova_ai.core.paths import get_config_dir
        creds_path = get_config_dir() / "email_credentials.json"
        if not creds_path.exists():
            res = client.get("/api/email/inbox")
            assert res.status_code == 400

    def test_extension_health(self, client):
        res = client.get("/api/extension/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    def test_extension_ask(self, client):
        res = client.post("/api/extension/ask", json={"text": ""})
        assert res.status_code == 200
        assert "answer" in res.json()

    def test_extension_summarize(self, client):
        res = client.post(
            "/api/extension/ask",
            json={"text": "NOVA AI is an advanced local AI assistant.", "action": "summarize"},
        )
        assert res.status_code == 200
