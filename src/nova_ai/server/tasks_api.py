"""Task Planner REST API routes.

Exposes plan creation, status polling, and Server-Sent Events streaming
for live DAG visualization in the frontend.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from nova_ai.engine.task_planner import (
    TaskPlanner,
    subscribe_to_plan,
    unsubscribe_from_plan,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# Global planner instance shared with the server
_planner: TaskPlanner | None = None


def get_planner() -> TaskPlanner:
    global _planner
    if _planner is None:
        _planner = TaskPlanner()
    return _planner


class CreatePlanRequest(BaseModel):
    goal: str
    tasks: list[dict[str, Any]]


@router.get("")
async def list_plans():
    """Return all active task plans with their status."""
    return {"plans": get_planner().get_all_plans()}


@router.post("")
async def create_plan(body: CreatePlanRequest):
    """Create and immediately execute a new task plan."""
    planner = get_planner()
    plan = planner.create_plan(body.goal, body.tasks)
    # Execute synchronously in a thread pool to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, planner.execute_plan, plan)
    return {"plan_id": plan.id, "status": plan.status.value, "progress": plan.progress}


@router.get("/{plan_id}")
async def get_plan(plan_id: str):
    """Return full plan detail including all subtask statuses."""
    detail = get_planner().get_plan_detail(plan_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")
    return detail


@router.post("/{plan_id}/cancel")
async def cancel_plan(plan_id: str):
    """Cancel all pending/running tasks in a plan."""
    success = get_planner().cancel_plan(plan_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")
    return {"plan_id": plan_id, "status": "cancelled"}


@router.get("/{plan_id}/stream")
async def stream_plan_events(plan_id: str):
    """Server-Sent Events stream for live task status updates.

    The client should connect here and listen for events of the form:
        data: {"type": "task_update", "task_id": "...", "status": "running"}
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    subscribe_to_plan(plan_id, queue)

    async def event_generator():
        try:
            # Send current state immediately
            detail = get_planner().get_plan_detail(plan_id)
            if detail:
                yield f"data: {json.dumps({'type': 'snapshot', **detail})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'error', 'message': f'Plan {plan_id!r} not found'})}\n\n"
                return

            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {payload}\n\n"
                    event = json.loads(payload)
                    if event.get("type") in ("plan_complete",):
                        break
                except asyncio.TimeoutError:
                    # Keep-alive ping
                    yield ": ping\n\n"
        finally:
            unsubscribe_from_plan(plan_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
