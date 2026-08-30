from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nova_ai.server.clipboard_router import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

@patch("nova_ai.server.clipboard_router._get_clipboard_text", return_value="Test clipboard")
def test_read_clipboard(mock_get):
    response = client.get("/api/clipboard/read")
    assert response.status_code == 200
    assert response.json() == {"text": "Test clipboard", "length": 14}

@patch("nova_ai.server.clipboard_router.ClipboardAITool.execute")
def test_process_clipboard(mock_execute):
    class MockResult:
        success = True
        content = "Translated text"
        metadata = {"action": "translate"}

    mock_execute.return_value = MockResult()

    response = client.post("/api/clipboard/process", json={
        "action": "translate",
        "text": "Hello",
        "language": "French"
    })

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["result"] == "Translated text"
    assert response.json()["action"] == "translate"
