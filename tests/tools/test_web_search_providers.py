import pytest
import os
from unittest.mock import patch, MagicMock

from nova_ai.tools.web_search import WebSearchTool
from nova_ai.server.search_router import router

from fastapi.testclient import TestClient
from fastapi import FastAPI


@pytest.fixture
def test_client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_searxng_parsing():
    tool = WebSearchTool()
    
    with patch("httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"title": "Test Title", "url": "https://test.com", "content": "Test content snippet"}
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        
        results = tool._searxng_search("test query", 1)
        
        assert len(results) == 1
        assert results[0]["title"] == "Test Title"
        assert results[0]["url"] == "https://test.com"
        assert results[0]["snippet"] == "Test content snippet"


def test_brave_parsing():
    tool = WebSearchTool()
    
    with patch("httpx.get") as mock_get, patch.dict(os.environ, {"BRAVE_API_KEY": "fake_key"}):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "web": {
                "results": [
                    {"title": "Brave Title", "url": "https://brave.com", "description": "Brave content snippet"}
                ]
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        
        results = tool._brave_search("test query", 1)
        
        assert len(results) == 1
        assert results[0]["title"] == "Brave Title"
        assert results[0]["url"] == "https://brave.com"
        assert results[0]["snippet"] == "Brave content snippet"


def test_search_router(test_client):
    with patch("nova_ai.tools.web_search.WebSearchTool.execute") as mock_execute:
        mock_res = MagicMock()
        mock_res.success = True
        mock_res.content = "raw content"
        mock_res.metadata = {
            "provider": "duckduckgo",
            "results": [{"title": "t", "url": "u", "snippet": "s"}]
        }
        mock_execute.return_value = mock_res
        
        response = test_client.post("/api/search", json={"query": "test query", "synthesize": False})
        
        assert response.status_code == 200
        data = response.json()
        assert data["provider"] == "duckduckgo"
        assert data["success"] is True
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "t"
