from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from nova_ai.server.app import create_app


@pytest.fixture
def test_client():
    app = create_app(engine=MagicMock(), model="test-model")
    return TestClient(app)

@patch("nova_ai.server.model_compare_router.asyncio.to_thread")
def test_compare_models(mock_to_thread, test_client):
    mock_to_thread.side_effect = ["Mock response 1", "Mock response 2"]

    response = test_client.post(
        "/api/compare",
        json={
            "models": ["model1", "model2"],
            "prompt": "Test prompt"
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert "comparison_id" in data
    assert data["prompt"] == "Test prompt"
    assert len(data["results"]) == 2
    assert data["results"][0]["model"] == "model1"
    assert data["results"][1]["model"] == "model2"
    assert data["results"][0]["success"] is True

def test_compare_models_empty_models(test_client):
    response = test_client.post(
        "/api/compare",
        json={
            "models": [],
            "prompt": "Test prompt"
        }
    )
    assert response.status_code == 400

def test_compare_models_empty_prompt(test_client):
    response = test_client.post(
        "/api/compare",
        json={
            "models": ["model1"],
            "prompt": ""
        }
    )
    assert response.status_code == 400

@patch("nova_ai.server.model_compare_router._get_db")
def test_vote_winner(mock_get_db, test_client):
    mock_conn = MagicMock()
    mock_get_db.return_value = mock_conn

    response = test_client.post(
        "/api/compare/vote",
        json={
            "comparison_id": "test_id",
            "winner_model": "model1",
            "prompt": "test prompt",
            "models_compared": ["model1", "model2"]
        }
    )

    assert response.status_code == 200
    assert response.json()["winner"] == "model1"
    mock_conn.execute.assert_called_once()
    mock_conn.commit.assert_called_once()

@patch("nova_ai.server.model_compare_router._get_db")
def test_list_votes(mock_get_db, test_client):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_cursor.fetchall.return_value = [
        {"id": "1", "comparison_id": "c1", "winner_model": "model1", "prompt": "p1", "models_compared": "[\"model1\", \"model2\"]", "timestamp": 123.4},
        {"id": "2", "comparison_id": "c2", "winner_model": "model1", "prompt": "p2", "models_compared": "[\"model1\", \"model2\"]", "timestamp": 123.5}
    ]
    mock_get_db.return_value = mock_conn

    response = test_client.get("/api/compare/votes")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["win_counts"]["model1"] == 2
