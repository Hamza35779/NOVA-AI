"""Clipboard AI REST API."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from nova_ai.tools.clipboard_ai import ClipboardAITool, _get_clipboard_text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/clipboard", tags=["clipboard"])


class ClipboardProcessRequest(BaseModel):
    action: str = "summarize"
    text: Optional[str] = None
    language: str = "English"
    copy_back: bool = False


@router.get("/read")
async def read_clipboard():
    text = _get_clipboard_text()
    return {"text": text, "length": len(text)}


@router.post("/process")
async def process_clipboard(body: ClipboardProcessRequest):
    tool = ClipboardAITool()
    res = tool.execute(
        action=body.action,
        text=body.text,
        language=body.language,
        copy_back=body.copy_back,
    )
    return {
        "success": res.success,
        "result": res.content,
        "action": body.action,
        "metadata": getattr(res, "metadata", {}),
    }
