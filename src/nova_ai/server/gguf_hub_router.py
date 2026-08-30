"""GGUF Model Hub API — direct Hugging Face download with SSE progress.

Provides endpoints for the Model Hub UI to:
- List the curated GGUF catalog with install status
- Download models from Hugging Face in the background
- Stream real-time download progress via SSE
- Delete locally cached models
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from nova_ai.engine.gguf import (
    GGUF_CATALOG,
    download_gguf_model,
    get_model_path,
    get_models_dir,
    list_installed_gguf_models,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/models/gguf", tags=["gguf_hub"])

# Active download tracking: task_id -> progress dict
_downloads: Dict[str, Dict[str, Any]] = {}


class DownloadRequest(BaseModel):
    model_id: str


@router.get("/catalog")
async def get_gguf_catalog() -> Dict[str, Any]:
    """Return the full GGUF catalog with per-model install state."""
    installed = set(list_installed_gguf_models())
    models_dir = get_models_dir()

    catalog = []
    for entry in GGUF_CATALOG:
        is_installed = entry["id"] in installed
        size_bytes = 0
        local_path = models_dir / entry["filename"]
        if is_installed and local_path.exists():
            size_bytes = local_path.stat().st_size

        catalog.append({
            **entry,
            "installed": is_installed,
            "local_path": str(local_path) if is_installed else None,
            "size_bytes": size_bytes,
            "engine": "gguf",
            "requires_ollama": False,
        })

    categories = [
        {"key": "all", "label": "All Models"},
        {"key": "fast", "label": "⚡ Fast & Light"},
        {"key": "general", "label": "🌟 General Purpose"},
        {"key": "coding", "label": "💻 Coding"},
        {"key": "reasoning", "label": "🧠 Reasoning"},
    ]

    return {
        "catalog": catalog,
        "categories": categories,
        "total_installed": len(installed),
        "models_dir": str(get_models_dir()),
        "engine": "gguf",
        "requires_ollama": False,
    }


@router.get("/installed")
async def list_installed() -> Dict[str, Any]:
    """List all locally installed GGUF models."""
    installed_ids = list_installed_gguf_models()
    models_dir = get_models_dir()

    result = []
    for model_id in installed_ids:
        entry = next((m for m in GGUF_CATALOG if m["id"] == model_id), None)
        if entry:
            path = models_dir / entry["filename"]
            result.append({
                "id": model_id,
                "name": entry["name"],
                "path": str(path),
                "size_bytes": path.stat().st_size if path.exists() else 0,
            })

    return {"installed": result, "count": len(result)}


@router.post("/download")
async def start_download(body: DownloadRequest) -> Dict[str, Any]:
    """Start a background download from Hugging Face Hub.

    Returns a ``task_id`` that can be polled via the SSE stream endpoint.
    """
    model_id = body.model_id
    task_id = f"gguf_{model_id.replace('-', '_').replace('.', '_')}"

    # Already downloaded?
    if get_model_path(model_id) is not None:
        return {"task_id": task_id, "model_id": model_id, "status": "already_installed"}

    # Already in progress?
    existing = _downloads.get(task_id)
    if existing and not existing.get("done"):
        return {"task_id": task_id, "model_id": model_id, "status": "in_progress"}

    _downloads[task_id] = {
        "model_id": model_id,
        "status": "starting",
        "percent": 0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
        "done": False,
        "error": None,
        "local_path": None,
    }

    def _worker() -> None:
        def _on_progress(downloaded: int, total: int) -> None:
            percent = int((downloaded / total) * 100) if total > 0 else 0
            _downloads[task_id].update({
                "status": "downloading",
                "downloaded_bytes": downloaded,
                "total_bytes": total,
                "percent": percent,
            })

        try:
            _downloads[task_id]["status"] = "connecting"
            path = download_gguf_model(model_id, progress_callback=_on_progress)
            _downloads[task_id].update({
                "status": "complete",
                "percent": 100,
                "done": True,
                "local_path": str(path),
            })
            logger.info("GGUF download complete: %s -> %s", model_id, path)
        except Exception as exc:
            logger.error("GGUF download failed for %s: %s", model_id, exc)
            _downloads[task_id].update({
                "status": "failed",
                "done": True,
                "error": str(exc),
            })

    thread = threading.Thread(target=_worker, daemon=True, name=f"gguf-dl-{model_id}")
    thread.start()

    return {"task_id": task_id, "model_id": model_id, "status": "initiated"}


@router.get("/download/{task_id}/progress")
async def stream_download_progress(task_id: str):
    """SSE stream of download progress for a given task_id."""
    async def _generator():
        while True:
            info = _downloads.get(task_id, {
                "status": "unknown",
                "percent": 0,
                "done": False,
                "error": f"No download task found: {task_id}",
            })
            yield f"data: {json.dumps(info)}\n\n"
            if info.get("done") or info.get("error"):
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/download/{task_id}/status")
async def get_download_status(task_id: str) -> Dict[str, Any]:
    """Poll the current download status without an SSE connection."""
    return _downloads.get(task_id, {"status": "not_found", "done": False})


@router.delete("/model/{model_id}")
async def delete_model(model_id: str) -> Dict[str, Any]:
    """Delete a locally cached GGUF model file."""
    path = get_model_path(model_id)
    if path is None or not path.exists():
        return {"success": False, "message": f"Model {model_id!r} is not installed."}

    try:
        path.unlink()
        logger.info("Deleted GGUF model: %s", path)
        return {"success": True, "message": f"Deleted {path.name}", "model_id": model_id}
    except OSError as exc:
        return {"success": False, "message": str(exc)}
