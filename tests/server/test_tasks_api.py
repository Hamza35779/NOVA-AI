"""Tests for the Task Planner REST API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class TestTaskPlannerAPI:
    @pytest.fixture
    def client(self):
        try:
            from nova_ai.server.app import create_app
            app = create_app(engine=None, model="dummy")
            return TestClient(app)
        except ImportError:
            from nova_ai.server.main import app
            return TestClient(app)

    def test_list_plans_empty(self, client):
        response = client.get("/api/tasks")
        assert response.status_code == 200
        data = response.json()
        assert "plans" in data

    def test_create_and_get_plan(self, client):
        payload = {
            "goal": "Test Goal",
            "tasks": [
                {"id": "t1", "title": "Step 1"},
                {"id": "t2", "title": "Step 2", "depends_on": ["t1"]},
            ],
        }
        response = client.post("/api/tasks", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "plan_id" in data
        plan_id = data["plan_id"]

        detail = client.get(f"/api/tasks/{plan_id}")
        assert detail.status_code == 200
        plan = detail.json()
        assert plan["goal"] == "Test Goal"
        assert len(plan["tasks"]) == 2

    def test_cancel_plan(self, client):
        payload = {"goal": "Cancel Test", "tasks": [{"id": "t1", "title": "Step"}]}
        create = client.post("/api/tasks", json=payload)
        plan_id = create.json()["plan_id"]
        cancel = client.post(f"/api/tasks/{plan_id}/cancel")
        # Already completed plans just return ok
        assert cancel.status_code in (200, 404)

    def test_get_nonexistent_plan(self, client):
        response = client.get("/api/tasks/nonexistent-plan-id")
        assert response.status_code == 404
