"""Conversation history REST API."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from nova_ai.server.chat_history_store import get_history_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/history", tags=["history"])


class CreateConvRequest(BaseModel):
    title: str = "New conversation"


class UpdateConvRequest(BaseModel):
    title: Optional[str] = None
    pinned: Optional[bool] = None


class AddMessageRequest(BaseModel):
    role: str
    content: str
    tool_calls: Optional[list] = None


@router.get("")
async def list_conversations(limit: int = 50, offset: int = 0):
    store = get_history_store()
    convs = store.list_conversations(limit=limit, offset=offset)
    return {"conversations": convs, "total": len(convs)}


@router.post("")
async def create_conversation(body: CreateConvRequest):
    store = get_history_store()
    conv = store.create_conversation(title=body.title)
    return conv


@router.get("/search")
async def search_history(q: str = Query(..., min_length=1)):
    store = get_history_store()
    results = store.search(q)
    return {"results": results, "query": q}


@router.get("/{conv_id}")
async def get_conversation(conv_id: str):
    store = get_history_store()
    conv = store.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = store.get_messages(conv_id)
    return {**conv, "messages": messages}


@router.put("/{conv_id}")
async def update_conversation(conv_id: str, body: UpdateConvRequest):
    store = get_history_store()
    conv = store.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    updated = store.update_conversation(conv_id, title=body.title, pinned=body.pinned)
    return updated


@router.delete("/{conv_id}")
async def delete_conversation(conv_id: str):
    store = get_history_store()
    ok = store.delete_conversation(conv_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": conv_id}


@router.post("/{conv_id}/messages")
async def add_message(conv_id: str, body: AddMessageRequest):
    store = get_history_store()
    conv = store.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msg = store.add_message(conv_id, role=body.role, content=body.content, tool_calls=body.tool_calls)
    return msg
