import pytest

# Create a minimal test app
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from nova_ai.server.model_hub_router import router

app = FastAPI()
app.include_router(router)

@pytest.mark.asyncio
async def test_get_model_catalog():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/models/hub/catalog")
        assert response.status_code == 200
        data = response.json()
        assert "catalog" in data
        assert "categories" in data
        assert "total_installed" in data
        assert len(data["catalog"]) > 0

@pytest.mark.asyncio
async def test_install_model():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/models/hub/install", json={"model_id": "mock_model:test"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "initiated"
        assert "task_id" in data
        task_id = data["task_id"]

        import asyncio
        # Wait a bit for the background task to run
        await asyncio.sleep(1)

        # Stream the SSE events
        async with client.stream("GET", f"/api/models/hub/install/{task_id}/stream") as stream_response:
            assert stream_response.status_code == 200

            found_done = False
            async for line in stream_response.aiter_lines():
                if not line.strip():
                    continue
                assert line.startswith("data: ")
                event_data = line[6:]
                import json
                info = json.loads(event_data)
                if info.get("done"):
                    found_done = True
                    break

            assert found_done
