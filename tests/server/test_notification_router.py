import asyncio
import os
import tempfile

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from nova_ai.notifications.notifier import get_notifier
from nova_ai.server.notification_router import router

app = FastAPI()
app.include_router(router)


@pytest.fixture(autouse=True)
def clear_db():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    notifier = get_notifier()
    notifier.db_path = path
    notifier._init_db()
    notifier.clear()
    yield
    notifier.clear()
    try:
        os.remove(path)
    except OSError:
        pass



@pytest.mark.asyncio
async def test_send_notification():
    async with AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/api/notifications",
            json={"title": "Test Title", "message": "Test Message", "urgency": "high"}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Test Title"
    assert data["message"] == "Test Message"
    assert data["urgency"] == "high"


@pytest.mark.asyncio
async def test_list_notifications():
    async with AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post(
            "/api/notifications",
            json={"title": "Test Title 1", "message": "Test Message 1"}
        )
        await ac.post(
            "/api/notifications",
            json={"title": "Test Title 2", "message": "Test Message 2"}
        )
        response = await ac.get("/api/notifications")
    assert response.status_code == 200
    data = response.json()
    assert len(data["notifications"]) == 2


@pytest.mark.asyncio
async def test_clear_notifications():
    async with AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post(
            "/api/notifications",
            json={"title": "Test Title", "message": "Test Message"}
        )

        response = await ac.get("/api/notifications")
        assert len(response.json()["notifications"]) == 1

        clear_response = await ac.post("/api/notifications/clear")
        assert clear_response.status_code == 200
        assert clear_response.json()["status"] == "cleared"

        response2 = await ac.get("/api/notifications")
        assert len(response2.json()["notifications"]) == 0


@pytest.mark.asyncio
async def test_sse_stream():
    from nova_ai.notifications.notifier import _sse_queues
    from nova_ai.server.notification_router import notification_stream

    response = await notification_stream()
    gen = response.body_iterator

    # Wait a tiny bit to ensure it registered
    await asyncio.sleep(0.01)

    assert len(_sse_queues) == 1

    # Trigger an event directly
    get_notifier().send(title="Stream Event", message="Hello SSE")

    # Get the first event from generator
    event_str = await gen.__anext__()

    assert "Stream Event" in event_str
    assert "Hello SSE" in event_str
