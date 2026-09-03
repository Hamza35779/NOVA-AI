"""Conversation tree REST API — fork, regenerate, race, prefer.

Backed by :class:`nova_ai.conversations.store.ConversationStore` (the
tree-shaped sibling of the linear chat history). Sibling answers —
created by forks, regenerations, or model races — are recorded as
preference pairs feeding the DPO lane.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from nova_ai.conversations.store import ConversationStore
from nova_ai.core.paths import get_config_dir

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/conversations", tags=["conversations"])

_DB_FILE = "conversations.db"


def _get_store() -> ConversationStore:
    return ConversationStore(get_config_dir() / _DB_FILE)


class CreateConversationRequest(BaseModel):
    title: str = "New conversation"


class AddMessageRequest(BaseModel):
    role: str = "user"
    content: str
    parent_id: Optional[str] = None  # None → hang off the conversation root
    model: str = ""
    engine: str = ""


class RegenerateRequest(BaseModel):
    """Create a new sibling for the parent's last assistant answer."""

    prompt_node_id: Optional[str] = None  # None → parent of the last assistant
    model: str = ""
    engine: str = ""


class PickSiblingRequest(BaseModel):
    chosen_node_id: str
    source: str = "regen"  # regen | fork


class RaceRequest(BaseModel):
    models: List[str]
    prompt_node_id: Optional[str] = None  # None → parent of the last assistant
    judge: bool = False  # auto-judge with the configured judge model
    temperature: float = 0.7
    max_tokens: int = 1024


class ForkRequest(BaseModel):
    node_id: str  # fork from this node: a new branch starting with its content


class FeedbackRequest(BaseModel):
    score: float  # e.g. 1.0 thumbs-up, 0.0 thumbs-down


def _tree(store: ConversationStore, conversation_id: str) -> Dict[str, Any]:
    """Render the whole conversation as a node tree (children keyed by id)."""
    with store._lock:  # noqa: SLF001 - single read snapshot
        rows = store._conn.execute(
            "SELECT id, conversation_id, parent_id, role, content, model, engine, "
            "created_at, metadata, feedback FROM conv_nodes "
            "WHERE conversation_id = ? ORDER BY created_at, id",
            (conversation_id,),
        ).fetchall()
    nodes = [store._row_to_node(r) for r in rows]
    by_parent: Dict[str, list[Dict[str, Any]]] = {}
    for node in nodes:
        by_parent.setdefault(node["parent_id"], []).append(node)
    return {"nodes": nodes, "children": by_parent}


@router.post("")
async def create_conversation(body: CreateConversationRequest):
    store = _get_store()
    conv = store.create_conversation(title=body.title)
    with store._lock:  # noqa: SLF001
        row = store._conn.execute(
            "SELECT id FROM conv_nodes WHERE conversation_id = ? "
            "AND parent_id = conversation_id",
            (conv["id"],),
        ).fetchone()
    conv["root_id"] = row["id"] if row else ""
    return conv


@router.get("")
async def list_conversations(limit: int = 50):
    store = _get_store()
    return {"conversations": store.list_conversations(limit=limit)}


@router.get("/{conv_id}/tree")
async def get_tree(conv_id: str):
    store = _get_store()
    convs = {c["id"] for c in store.list_conversations(limit=10000)}
    if conv_id not in convs:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _tree(store, conv_id)


@router.post("/{conv_id}/messages")
async def add_message(conv_id: str, body: AddMessageRequest):
    store = _get_store()
    convs = {c["id"] for c in store.list_conversations(limit=10000)}
    if conv_id not in convs:
        raise HTTPException(status_code=404, detail="Conversation not found")
    parent_id = body.parent_id
    if not parent_id:
        with store._lock:  # noqa: SLF001
            row = store._conn.execute(
                "SELECT id FROM conv_nodes WHERE conversation_id = ? "
                "AND parent_id = conversation_id",
                (conv_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Conversation root missing")
        parent_id = row["id"]
    elif store.get_node(parent_id) is None:
        raise HTTPException(status_code=404, detail="Parent node not found")
    node_id = store.add_message(
        conv_id,
        parent_id,
        body.role,
        body.content,
        model=body.model,
        engine=body.engine,
    )
    return {"node_id": node_id, "parent_id": parent_id, "role": body.role}


@router.post("/{conv_id}/fork")
async def fork_conversation(conv_id: str, body: ForkRequest):
    """Fork at *node_id*: the path to that node becomes its own branch tip.

    Forking copies nothing — the tree *is* the fork. The new node carries
    the same content/role and a metadata marker; subsequent messages hang
    off it, leaving the original branch untouched.
    """
    store = _get_store()
    node = store.get_node(body.node_id)
    if node is None or node["conversation_id"] != conv_id:
        raise HTTPException(status_code=404, detail="Node not found")
    fork_id = store.add_message(
        conv_id,
        node["parent_id"],
        node["role"],
        node["content"],
        model=node["model"],
        engine=node["engine"],
        metadata={**(node["metadata"] or {}), "fork_of": node["id"]},
    )
    return {"fork_node_id": fork_id, "forked_from": node["id"]}


@router.post("/{conv_id}/regenerate")
async def regenerate(conv_id: str, request: Request, body: RegenerateRequest):
    """Generate a fresh sibling answer for a prompt node.

    ``prompt_node_id`` empty → the parent of the conversation's last
    assistant answer (the common "regenerate" button). The answer is
    generated via ``app.state.engine``; picking between the old and new
    answer (``/nodes/{id}/pick``) records the preference pair.
    """
    store = _get_store()
    engine = request.app.state.engine
    if engine is None:
        raise HTTPException(status_code=503, detail="No engine loaded")
    try:
        prompt_node_id = _resolve_prompt_node(store, conv_id, body.prompt_node_id or "")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    prompt_path = [
        m for m in store.path_to_root(prompt_node_id) if m["role"] != "system"
    ]
    from nova_ai.core.types import Message, Role

    messages = [
        Message(role=Role(m["role"]), content=m.get("content", ""))
        for m in prompt_path
    ]
    model = body.model or getattr(request.app.state, "model", "") or ""
    try:
        response = engine.generate(
            messages, model=model, temperature=0.7, max_tokens=1024
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"generation failed: {exc}") from exc

    content = response.get("content", "") if isinstance(response, dict) else str(response)
    node_id = store.add_message(
        conv_id,
        prompt_node_id,
        "assistant",
        content,
        model=model,
        engine=body.engine or getattr(engine, "engine_id", ""),
        metadata={"regenerated": True},
    )
    siblings = [
        c
        for c in store.children(prompt_node_id)
        if c["role"] == "assistant" and c["id"] != node_id
    ]
    return {
        "node_id": node_id,
        "prompt_node_id": prompt_node_id,
        "content": content,
        "sibling_ids": [s["id"] for s in siblings],
    }


@router.post("/{conv_id}/race")
async def race(conv_id: str, request: Request, body: RaceRequest):
    """Race 2+ models on one prompt node; winner becomes the active sibling."""
    if len(body.models) < 2:
        raise HTTPException(
            status_code=400, detail="Racing requires at least two models"
        )
    store = _get_store()
    engine = request.app.state.engine
    if engine is None:
        raise HTTPException(status_code=503, detail="No engine loaded")
    from nova_ai.conversations.racer import race_models

    judge = None
    if body.judge:
        judge = _build_judge(request)
    try:
        result = race_models(
            store=store,
            parent_node_id=_resolve_prompt_node(
                store, conv_id, body.prompt_node_id or ""
            ),
            models=body.models,
            engine=engine,
            judge=judge,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


@router.post("/nodes/{node_id}/feedback")
async def node_feedback(node_id: str, body: FeedbackRequest):
    store = _get_store()
    if not store.set_feedback(node_id, body.score):
        raise HTTPException(status_code=404, detail="Node not found")
    return {"node_id": node_id, "feedback": body.score}


@router.post("/nodes/{node_id}/pick")
async def pick_sibling(node_id: str, body: PickSiblingRequest):
    """Mark one sibling chosen and its sisters rejected → preference pair."""
    store = _get_store()
    node = store.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    siblings = [
        c
        for c in store.children(node["parent_id"])
        if c["role"] == "assistant" and c["id"] != node_id
    ]
    if not siblings:
        raise HTTPException(
            status_code=400, detail="No sibling answers to prefer against"
        )
    prompt_path = store.path_to_root(node["parent_id"])
    pair_id = store.add_sibling_choice(
        node["conversation_id"],
        [m for m in prompt_path if m["role"] != "system"],
        node_id,
        [s["id"] for s in siblings],
        source=body.source,
    )
    return {"pair_id": pair_id, "chosen": node_id, "rejected": [s["id"] for s in siblings]}


@router.get("/preference-pairs")
async def list_preference_pairs(limit: int = 200, conversation_id: Optional[str] = None):
    store = _get_store()
    pairs = store.list_preference_pairs(
        conversation_id=conversation_id, limit=limit
    )
    return {"pairs": pairs, "total": len(pairs)}


def _resolve_prompt_node(store: ConversationStore, conv_id: str, node_id: str) -> str:
    """Validate a prompt node, or default to the conversation's last user node.

    Racing/regenerating answer the *last user message* by default — no
    assistant node needs to exist yet (unlike the client-side regenerate
    button, which passes an explicit prompt node).
    """
    if node_id:
        node = store.get_node(node_id)
        if node is None or node["conversation_id"] != conv_id:
            raise ValueError(f"unknown prompt node: {node_id}")
        return node_id
    with store._lock:  # noqa: SLF001
        row = store._conn.execute(
            "SELECT id FROM conv_nodes WHERE conversation_id = ? "
            "AND role = 'user' ORDER BY created_at DESC, id DESC LIMIT 1",
            (conv_id,),
        ).fetchone()
    if row is None:
        raise ValueError("no user message to answer")
    return row["id"]


def _build_judge(request: Request):
    """Judge backend from app.state (engine-backed, first-line YES/NO)."""
    from nova_ai.evals.backends.nova_direct import NovaDirectBackend

    return NovaDirectBackend()


def default_db_path() -> Path:
    return get_config_dir() / _DB_FILE
