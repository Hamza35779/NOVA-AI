"""Notifications REST API and SSE stream endpoint."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from nova_ai.notifications.notifier import (
    get_notifier,
    register_notification_subscriber,
    unregister_notification_subscriber,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class SendNotificationRequest(BaseModel):
    title: str
    message: str
    urgency: str = "normal"  # low | normal | high
    action_url: Optional[str] = None


@router.get("")
async def list_notifications(limit: int = 50):
    notifier = get_notifier()
    return {"notifications": notifier.list_recent(limit)}


@router.post("")
async def send_notification(body: SendNotificationRequest):
    notifier = get_notifier()
    notif = notifier.send(
        title=body.title,
        message=body.message,
        urgency=body.urgency,
        action_url=body.action_url,
    )
    return notif


@router.post("/clear")
async def clear_notifications():
    notifier = get_notifier()
    notifier.clear()
    return {"status": "cleared"}


@router.get("/stream")
async def notification_stream():
    """SSE stream of real-time notifications for desktop alerts."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    register_notification_subscriber(queue)

    async def event_generator():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            unregister_notification_subscriber(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
