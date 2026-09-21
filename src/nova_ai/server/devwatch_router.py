"""Dev-watch diagnostics REST API.

Stores recent ``nova dev-watch`` run results so the Dashboard can display
build/test health. The CLI posts runs here when the server is reachable;
the endpoint set is deliberately tiny.

Two storage layers:
- an in-process ring (fast, bounded to 50 runs) for the live panel;
- a SQLite store (``~/.nova_ai/devwatch.db``) that mirrors every run so
  history survives server restarts. On startup the ring is rehydrated
  from SQLite. Persistence is best-effort: a broken store never blocks
  recording or serving runs.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from nova_ai.server.devwatch_store import DevWatchStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/devwatch", tags=["devwatch"])

_MAX_RUNS = 50
_lock = threading.Lock()
_runs: Deque[Dict[str, str]] = deque(maxlen=_MAX_RUNS)

# Module-level store, created lazily so importing this module (e.g. from
# tests that never start the app) does not touch the filesystem.
# _store_disabled distinguishes "not created yet" (lazy-init on first POST)
# from "explicitly disabled" (tests, persistence off): when True the lazy
# path is skipped entirely instead of re-creating the real user DB behind
# the test's back.
_store: Optional[DevWatchStore] = None
_store_disabled = False
_store_lock = threading.Lock()


def _get_store() -> Optional[DevWatchStore]:
    global _store
    if _store is not None or _store_disabled:
        return _store
    with _store_lock:
        if _store is None and not _store_disabled:
            try:
                store = DevWatchStore()
                if store.available:
                    _hydrate_from_store(store)
                    _store = store
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("devwatch persistence unavailable: %s", exc)
    return _store


def _hydrate_from_store(store: DevWatchStore) -> None:
    """Seed the in-memory ring with the most recent persisted runs."""
    try:
        persisted = store.list_recent(limit=_MAX_RUNS)
    except Exception:  # pragma: no cover - defensive
        return
    with _lock:
        _runs.clear()
        for entry in reversed(persisted):  # oldest first -> ring order
            _runs.append(entry)


def warm_store() -> None:
    """Create the SQLite store and rehydrate the ring (call at startup)."""
    _get_store()


def reset_store_for_tests() -> None:
    """Drop the cached store and re-enable lazy init (default state)."""
    global _store, _store_disabled
    with _store_lock:
        if _store is not None:
            _store.close()
        _store = None
        _store_disabled = False
    with _lock:
        _runs.clear()


def disable_store_for_tests() -> None:
    """Run without persistence (pure in-memory ring, like pre-persistence)."""
    global _store, _store_disabled
    with _store_lock:
        if _store is not None:
            _store.close()
        _store = None
        _store_disabled = True
    with _lock:
        _runs.clear()


def set_store_for_tests(store: Optional[DevWatchStore]) -> None:
    """Inject a store directly (tests use a temp-path or :memory: DB)."""
    global _store, _store_disabled
    with _store_lock:
        if _store is not None:
            _store.close()
        _store = store
        _store_disabled = False
    with _lock:
        _runs.clear()
        if store is not None and store.available:
            for entry in reversed(store.list_recent(limit=_MAX_RUNS)):
                _runs.append(entry)


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
    store = _get_store()
    if store is not None:
        try:
            store.record(entry)
        except Exception as exc:  # persistence must never break recording
            logger.debug("devwatch persist failed: %s", exc)
    return {"success": True, "recorded": entry}
