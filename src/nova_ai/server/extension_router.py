"""Browser extension REST API — CORS-enabled endpoint for NOVA AI browser extension."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/extension", tags=["extension"])


class AskRequest(BaseModel):
    text: str
    context_url: Optional[str] = None
    action: str = "ask"   # ask | summarize | translate | explain
    language: Optional[str] = None


@router.post("/ask")
async def extension_ask(body: AskRequest):
    """Handle a question or action from the browser extension."""
    if not body.text.strip():
        return {"answer": "Please provide some text."}

    # Build prompt based on action
    if body.action == "summarize":
        prompt = f"Summarize the following text concisely in 3-5 bullet points:\n\n{body.text}"
    elif body.action == "explain":
        prompt = f"Explain the following in simple terms:\n\n{body.text}"
    elif body.action == "translate":
        lang = body.language or "English"
        prompt = f"Translate the following to {lang}:\n\n{body.text}"
    else:
        context = f"\n\nPage URL: {body.context_url}" if body.context_url else ""
        prompt = f"{body.text}{context}"

    try:
        from nova_ai.sdk import Nova
        answer = Nova().ask(prompt)
    except Exception as exc:
        logger.error("Extension ask failed: %s", exc)
        answer = f"NOVA AI is unavailable: {exc}"

    return {
        "answer": answer,
        "action": body.action,
        "context_url": body.context_url,
    }


@router.get("/health")
async def extension_health():
    """Health check for the browser extension to detect if NOVA is running."""
    return {"status": "ok", "service": "NOVA AI", "version": "1.0.3"}
