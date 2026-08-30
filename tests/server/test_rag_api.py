"""Tests for the RAG document upload and chat API."""
from __future__ import annotations
import io
import pytest
from fastapi.testclient import TestClient


class TestDocAPI:
    @pytest.fixture
    def client(self):
        from unittest.mock import MagicMock
        engine = MagicMock()
        engine.engine_id = "mock"
        
        try:
            from nova_ai.server.app import create_app
            app = create_app(engine=engine, model="test")
        except ImportError:
            from nova_ai.server.main import create_app
            app = create_app(engine=engine, model="test")
        return TestClient(app)

    def test_list_docs_empty(self, client):
        res = client.get("/v1/connectors/upload/docs")
        assert res.status_code == 200
        assert "documents" in res.json()

    def test_ingest_text_file(self, client):
        content = b"NOVA AI is an advanced AI assistant with 55 tools."
        res = client.post(
            "/v1/connectors/upload/ingest/files",
            files=[("files", ("test.txt", io.BytesIO(content), "text/plain"))],
        )
        assert res.status_code == 200
        assert res.json()["chunks_added"] >= 1

    def test_doc_chat_no_docs(self, client):
        res = client.post(
            "/v1/connectors/upload/chat",
            json={"query": "What is NOVA AI?", "doc_ids": [], "top_k": 3},
        )
        assert res.status_code == 200
        assert "answer" in res.json()

    def test_delete_nonexistent_doc(self, client):
        res = client.delete("/v1/connectors/upload/docs/nonexistent-doc-id")
        assert res.status_code == 404
