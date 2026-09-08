"""Dev-watch diagnostics REST API.

Stores recent ``nova dev-watch`` run results (in-process) so the
Dashboard can display build/test health. The CLI posts runs here when
the server is reachable; the endpoint set is deliberately tiny.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/devwatch", tags=["devwatch"])

_MAX_RUNS = 50
_lock = threading.Lock()
_runs: Deque[Dict[str, str]] = deque(maxlen=_MAX_RUNS)


class DevWatchRunPayload(BaseModel):
    command: str
    status: str  # "pass" | "fail"
    returncode: int = 0
    failure_type: Optional[str] = None
    output: str = ""
    suggestion: str = ""
    at: Optional[str] = None  # ISO timestamp; server fills if absent


@router.get("/runs")
async def list_runs(limit: int = 20) -> Dict[str, object]:
    """Most recent dev-watch runs, newest first."""
    with _lock:
        runs = list(_runs)
    runs.reverse()
    return {"runs": runs[: max(1, min(limit, _MAX_RUNS))]}


@router.post("/runs")
async def record_run(payload: DevWatchRunPayload) -> Dict[str, object]:
    """Record one dev-watch run result (posted by the CLI)."""
    entry = payload.model_dump()
    if not entry.get("at"):
        entry["at"] = datetime.now(timezone.utc).isoformat()
    with _lock:
        _runs.append(entry)
    return {"success": True, "recorded": entry}
