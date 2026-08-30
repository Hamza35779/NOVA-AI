"""Persona & System Prompt REST API with preset management."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nova_ai.core.paths import get_config_dir

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/personas", tags=["personas"])

_DB_FILE = "personas.db"

BUILTIN_PRESETS = [
    {
        "id": "preset_default",
        "name": "Default NOVA",
        "avatar": "✨",
        "description": "Helpful, concise, accurate AI assistant with direct answers.",
        "system_prompt": "You are NOVA AI, an intelligent, helpful, and concise AI assistant. Provide direct, natural, and clear responses without robotic fluff.",
        "temperature": 0.7,
        "is_preset": True,
    },
    {
        "id": "preset_engineer",
        "name": "Senior Software Architect",
        "avatar": "💻",
        "description": "Expert in software architecture, clean code, performance, and modern toolchains.",
        "system_prompt": "You are a Principal Software Engineer and Architect. Provide production-ready, clean, idiomatic code. Explain design decisions, edge cases, and performance tradeoffs.",
        "temperature": 0.3,
        "is_preset": True,
    },
    {
        "id": "preset_researcher",
        "name": "Deep Researcher",
        "avatar": "🔬",
        "description": "Thorough, analytical thinker providing evidence-backed deep dives.",
        "system_prompt": "You are a scientific and market research analyst. Provide deep, structured analysis with source references, counter-arguments, and structured data tables.",
        "temperature": 0.4,
        "is_preset": True,
    },
    {
        "id": "preset_executive",
        "name": "Executive Advisor",
        "avatar": "👔",
        "description": "Strategic, high-level communicator focused on business impact and decisions.",
        "system_prompt": "You are a senior executive advisor. Format responses with executive summaries, key risks, ROI analysis, and clear decision frameworks.",
        "temperature": 0.5,
        "is_preset": True,
    },
    {
        "id": "preset_tutor",
        "name": "Socratic Tutor",
        "avatar": "🎓",
        "description": "Encourages deep understanding through guidance and insightful questions.",
        "system_prompt": "You are a Socratic tutor. Break complex concepts down into intuitive mental models with step-by-step guidance and practical analogies.",
        "temperature": 0.8,
        "is_preset": True,
    },
]


class CreatePersonaRequest(BaseModel):
    name: str
    description: str
    system_prompt: str
    avatar: str = "🤖"
    temperature: float = 0.7


class UpdatePersonaRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    avatar: Optional[str] = None
    temperature: Optional[float] = None


def _get_db():
    db_path = get_config_dir() / _DB_FILE
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS personas (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            avatar TEXT NOT NULL,
            description TEXT NOT NULL,
            system_prompt TEXT NOT NULL,
            temperature REAL NOT NULL DEFAULT 0.7,
            created_at REAL NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()
    return conn


@router.get("")
async def list_personas():
    """List all available personas (built-in presets + custom personas)."""
    conn = _get_db()
    rows = conn.execute("SELECT * FROM personas ORDER BY created_at DESC").fetchall()
    custom = [
        {
            "id": r["id"],
            "name": r["name"],
            "avatar": r["avatar"],
            "description": r["description"],
            "system_prompt": r["system_prompt"],
            "temperature": r["temperature"],
            "is_preset": False,
            "is_active": bool(r["is_active"]),
        }
        for r in rows
    ]

    active_id = "preset_default"
    for c in custom:
        if c["is_active"]:
            active_id = c["id"]

    all_personas = BUILTIN_PRESETS + custom
    return {"personas": all_personas, "active_id": active_id}


@router.post("")
async def create_persona(body: CreatePersonaRequest):
    """Create a new custom persona."""
    conn = _get_db()
    persona_id = str(uuid.uuid4())[:8]
    now = time.time()
    conn.execute(
        "INSERT INTO personas (id, name, avatar, description, system_prompt, temperature, created_at, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
        (persona_id, body.name, body.avatar, body.description, body.system_prompt, body.temperature, now),
    )
    conn.commit()
    return {
        "id": persona_id,
        "name": body.name,
        "avatar": body.avatar,
        "description": body.description,
        "system_prompt": body.system_prompt,
        "temperature": body.temperature,
        "is_preset": False,
        "is_active": False,
    }


@router.put("/{persona_id}")
async def update_persona(persona_id: str, body: UpdatePersonaRequest):
    """Update custom persona fields."""
    if persona_id.startswith("preset_"):
        raise HTTPException(status_code=400, detail="Cannot edit built-in presets")

    conn = _get_db()
    row = conn.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Persona not found")

    fields = []
    values = []
    if body.name is not None:
        fields.append("name = ?")
        values.append(body.name)
    if body.avatar is not None:
        fields.append("avatar = ?")
        values.append(body.avatar)
    if body.description is not None:
        fields.append("description = ?")
        values.append(body.description)
    if body.system_prompt is not None:
        fields.append("system_prompt = ?")
        values.append(body.system_prompt)
    if body.temperature is not None:
        fields.append("temperature = ?")
        values.append(body.temperature)

    if fields:
        values.append(persona_id)
        conn.execute(f"UPDATE personas SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()

    updated = conn.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
    return dict(updated)


@router.delete("/{persona_id}")
async def delete_persona(persona_id: str):
    """Delete a custom persona."""
    if persona_id.startswith("preset_"):
        raise HTTPException(status_code=400, detail="Cannot delete built-in presets")

    conn = _get_db()
    res = conn.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
    conn.commit()
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="Persona not found")
    return {"deleted": persona_id}


@router.post("/active/{persona_id}")
async def set_active_persona(persona_id: str):
    """Set the currently active persona."""
    conn = _get_db()
    conn.execute("UPDATE personas SET is_active = 0")
    if not persona_id.startswith("preset_"):
        conn.execute("UPDATE personas SET is_active = 1 WHERE id = ?", (persona_id,))
    conn.commit()
    return {"active_id": persona_id}
