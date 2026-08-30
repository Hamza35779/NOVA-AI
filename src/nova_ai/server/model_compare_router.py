"""Model Comparison API — side-by-side inference and voting."""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nova_ai.core.paths import get_config_dir

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/compare", tags=["compare"])

_DB_FILE = "model_comparisons.db"


class CompareRequest(BaseModel):
    models: List[str]
    prompt: str
    system_prompt: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 512


class VoteRequest(BaseModel):
    comparison_id: str
    winner_model: str
    prompt: str
    models_compared: List[str]


def _get_db():
    db_path = get_config_dir() / _DB_FILE
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS comparison_votes (
            id TEXT PRIMARY KEY,
            comparison_id TEXT NOT NULL,
            winner_model TEXT NOT NULL,
            prompt TEXT NOT NULL,
            models_compared TEXT NOT NULL,
            timestamp REAL NOT NULL
        );
    """)
    conn.commit()
    return conn


@router.post("")
async def compare_models(body: CompareRequest) -> Dict[str, Any]:
    """Execute completions across 2-4 models in parallel and track performance."""
    if not body.models:
        raise HTTPException(status_code=400, detail="Must specify at least one model")
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    comparison_id = str(uuid.uuid4())[:8]

    async def _run_model(model_name: str) -> Dict[str, Any]:
        start = time.perf_counter()
        try:
            from nova_ai.sdk import Nova
            nova = Nova()
            prompt_text = body.prompt
            if body.system_prompt:
                prompt_text = f"{body.system_prompt}\n\nUser: {body.prompt}"

            response = await asyncio.to_thread(nova.ask, prompt_text, model=model_name)
            latency_ms = (time.perf_counter() - start) * 1000
            token_count = len(response.split())
            tokens_per_sec = (token_count / (latency_ms / 1000.0)) if latency_ms > 0 else 0
            return {
                "model": model_name,
                "response": response,
                "latency_ms": round(latency_ms, 1),
                "tokens": token_count,
                "tokens_per_sec": round(tokens_per_sec, 1),
                "success": True,
            }
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            return {
                "model": model_name,
                "response": f"Error running model {model_name}: {exc}",
                "latency_ms": round(latency_ms, 1),
                "tokens": 0,
                "tokens_per_sec": 0,
                "success": False,
            }

    tasks = [_run_model(m) for m in body.models[:4]]
    results = await asyncio.gather(*tasks)

    return {
        "comparison_id": comparison_id,
        "prompt": body.prompt,
        "results": results,
    }


@router.post("/vote")
async def vote_winner(body: VoteRequest):
    """Cast vote for the superior model in a comparison."""
    conn = _get_db()
    vote_id = str(uuid.uuid4())[:8]
    conn.execute(
        "INSERT INTO comparison_votes (id, comparison_id, winner_model, prompt, models_compared, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (vote_id, body.comparison_id, body.winner_model, body.prompt, json.dumps(body.models_compared), time.time()),
    )
    conn.commit()

    # Record preference in routing feedback store
    try:
        from nova_ai.engine.router_learning import get_feedback_store
        store = get_feedback_store()
        store.record_feedback(
            message_id=body.comparison_id,
            query_content=body.prompt,
            tier_chosen="medium",
            correct_tier="large" if "32b" in body.winner_model.lower() or "pro" in body.winner_model.lower() else "medium",
        )
    except Exception:
        pass

    return {"status": "recorded", "vote_id": vote_id, "winner": body.winner_model}


@router.get("/votes")
async def list_votes(limit: int = 50):
    """List recent comparison votes and win rates."""
    conn = _get_db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM comparison_votes ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
    votes = [dict(r) for r in rows]

    # Aggregate win counts
    counts = {}
    for v in votes:
        w = v.get("winner_model", "")
        counts[w] = counts.get(w, 0) + 1

    return {"votes": votes, "win_counts": counts, "total": len(votes)}
