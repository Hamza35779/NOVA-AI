"""The consolidation pipeline — the sleep cycle itself.

``run_consolidation`` mines recent traces into clusters, asks the local
model to distill each cluster into atomic facts, deduplicates and
resolves contradictions against the existing fact base (recency +
confidence win, the loser is superseded), decays stale facts, and
records a run summary.

The LLM is injected via the ``llm`` seam (anything with a
``generate(prompt) -> str`` method); tests supply fakes, production
uses :class:`~nova_ai.evals.backends.nova_direct.NovaDirectBackend`.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from nova_ai.memory.consolidation.cluster import SessionMiner
from nova_ai.memory.consolidation.store import ConsolidationRunStore, FactStore

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
You are a memory-consolidation engine. Below is a cluster of related \
conversations between a user and their AI assistant. Distill durable, \
atomic facts about the user (preferences, project context, decisions, \
corrections) into strict JSON.

Rules:
- Output ONLY a JSON array. No prose, no markdown fences.
- Each element: {{"content": str, "topic": str, "confidence": float}}
- "content" is one self-contained fact in third person ("The user prefers ...").
- "topic" is a short slug like "editor", "deployment", "style".
- "confidence" is 0.0-1.0. One-off speculation gets < 0.5.
- Never invent facts not supported by the conversations.

Conversations:
{conversations}
"""


def default_llm(config: Any) -> Any:
    """Build the production LLM backend for fact extraction."""
    from nova_ai.evals.backends.nova_direct import NovaDirectBackend

    engine_key = getattr(config, "judge_engine", "") or "local"
    return NovaDirectBackend(engine_key=engine_key)


def run_consolidation(
    *,
    trace_store: Any,
    fact_store: FactStore,
    config: Any,
    run_store: Optional[ConsolidationRunStore] = None,
    consolidation_root: Optional[Path] = None,
    llm: Optional[Any] = None,
    embedder: Optional[Any] = None,
    trigger: str = "manual",
    config_obj: Optional[Any] = None,
) -> dict[str, Any]:
    """Run one consolidation cycle and return its summary.

    Parameters
    ----------
    trace_store :
        Object with ``list_traces()`` (typically ``TraceStore``).
    fact_store :
        The fact base to write into.
    config :
        ``[learning.consolidation]`` settings (``ConsolidationConfig``).
    run_store :
        Optional run history store.
    llm :
        Injection seam for the extraction model; ``generate(prompt) -> str``.
    embedder :
        Injection seam for clustering; ``embed(texts) -> vectors``.
    trigger :
        What started this run (``manual`` | ``scheduled`` | ``auto``).
    config_obj :
        Optional full ``NovaConfig`` for resolving the default judge model.
    """
    run_id = f"consol_{uuid.uuid4().hex[:12]}"

    def _fail(error: str) -> dict[str, Any]:
        logger.warning("[consolidate] failed: %s", error)
        if run_store is not None:
            run_store.finish_run(run_id, status="failed", error=error)
        return {"status": "failed", "run_id": run_id, "error": error}

    if run_store is None and consolidation_root is not None:
        run_store = ConsolidationRunStore(consolidation_root / "runs.db")
    if run_store is not None and run_store.is_running():
        # Checked *before* starting our own run — otherwise the guard
        # would trip on itself.
        return _fail("another consolidation run is already in flight")
    if run_store is not None:
        run_store.start_run(run_id, trigger=trigger)

    if not getattr(config, "enabled", False):
        return _fail("learning.consolidation.enabled is false")

    if llm is None:
        llm = default_llm(config_obj or config)

    # --- Mine clusters ------------------------------------------------------
    miner = SessionMiner(
        trace_store,
        embedder=embedder,
    )
    clusters = miner.mine(
        min_cluster_size=max(1, int(getattr(config, "min_session_messages", 6) // 2)),
    )
    if not clusters:
        summary = {
            "status": "skipped",
            "reason": "no clusters large enough to consolidate",
        }
        if run_store is not None:
            run_store.finish_run(run_id, status="completed", summary=summary)
        return {"status": "skipped", "run_id": run_id, **summary}

    # --- Distill facts ------------------------------------------------------
    max_facts = int(getattr(config, "max_facts_per_run", 50))
    existing = fact_store.active_facts()
    facts_added = 0
    facts_superseded = 0
    superseded_ids: list[str] = []

    for cluster in clusters:
        if facts_added >= max_facts:
            break
        prompt = _EXTRACTION_PROMPT.format(
            conversations=_render_cluster(cluster),
        )
        try:
            raw = llm.generate(prompt)
        except Exception as exc:
            logger.warning("[consolidate] extraction LLM failed: %s", exc)
            continue
        extracted = _parse_facts(raw)
        for item in extracted[: max_facts - facts_added]:
            fact_id, outcome = _integrate_fact(
                fact_store,
                content=item.get("content", ""),
                topic=item.get("topic", cluster["topic_hint"]),
                confidence=float(item.get("confidence", 0.5)),
                trace_ids=cluster["trace_ids"],
                existing=existing,
            )
            if outcome == "superseded":
                facts_added += 1
                facts_superseded += 1
                if fact_id:
                    superseded_ids.append(fact_id)
                existing = fact_store.active_facts()
            elif outcome == "added":
                facts_added += 1
                existing = fact_store.active_facts()
            # "deduped"/"skipped" count as neither an add nor a supersession.

    # --- Decay --------------------------------------------------------------
    decay_days = float(getattr(config, "decay_days", 90))
    decayed = fact_store.decay(older_than_days=decay_days)

    summary = {
        "clusters": len(clusters),
        "facts_added": facts_added,
        "facts_superseded": facts_superseded,
        "decayed": decayed,
    }
    if run_store is not None:
        run_store.finish_run(run_id, status="completed", summary=summary)
    return {"status": "completed", "run_id": run_id, **summary}


def _render_cluster(cluster: dict[str, Any]) -> str:
    lines: list[str] = []
    for msg in cluster["messages"]:
        feedback = msg.get("feedback")
        tag = f" (feedback={feedback:.2f})" if isinstance(feedback, (int, float)) else ""
        lines.append(f"[{msg['role']}{tag}] {msg['content'][:600]}")
    return "\n".join(lines)


def _parse_facts(raw: str) -> list[dict[str, Any]]:
    """Parse the extraction LLM's JSON array; tolerate fence wrappers."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("content")]


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def _integrate_fact(
    fact_store: FactStore,
    *,
    content: str,
    topic: str,
    confidence: float,
    trace_ids: list[str],
    existing: list[dict[str, Any]],
) -> tuple[Optional[str], str]:
    """Add a fact, deduping and resolving contradictions.

    Returns ``(fact_id, outcome)`` where outcome is one of:

    - ``"added"`` — a brand-new fact was stored.
    - ``"deduped"`` — it duplicated an existing fact (touched instead).
    - ``"superseded"`` — new fact stored and a contradictory prior was
      overturned (recency + confidence win).
    - ``"skipped"`` — empty content.
    """
    content = content.strip()
    if not content:
        return None, "skipped"
    norm = _normalize(content)

    # Pass 1 — dedup wins over contradiction: an identical fact may
    # coexist with a contradictory one (both kept when unconfident), and
    # re-proposing it must touch the copy, not add a third.
    for prior in existing:
        prior_norm = _normalize(prior["content"])
        if not prior_norm:
            continue
        if norm == prior_norm or norm in prior_norm or prior_norm in norm:
            fact_store.touch(prior["id"])
            return prior["id"], "deduped"

    # Pass 2 — contradiction: same topic, opposing statement. Resolve by
    # recency + confidence — the newer, more confident fact wins and the
    # old one is superseded.
    for prior in existing:
        prior_norm = _normalize(prior["content"])
        if not prior_norm:
            continue
        if topic and prior["topic"] == topic and _contradicts(norm, prior_norm):
            new_id = fact_store.add_fact(
                content,
                topic=topic,
                confidence=confidence,
                source_trace_ids=trace_ids,
            )
            if confidence > prior["confidence"]:
                fact_store.supersede(prior["id"], by_id=new_id)
                return new_id, "superseded"
            # Not confident enough to overturn — record both, flag low.
            fact_store.set_status(new_id, "active")
            fact_store.touch(new_id)
            return new_id, "added"

    return (
        fact_store.add_fact(
            content,
            topic=topic,
            confidence=confidence,
            source_trace_ids=trace_ids,
        ),
        "added",
    )


_NEGATIONS = (" not ", " never ", " no longer ", " doesn't ", " don't ", " isn't ")


def _contradicts(a: str, b: str) -> bool:
    """Cheap heuristic contradiction check.

    Two facts contradict when they share a keyword stem but disagree on
    negation. Deliberately conservative: missing a contradiction keeps
    both facts (safe); inventing one would delete knowledge (unsafe).
    """
    a_neg = any(neg in f" {a} " for neg in _NEGATIONS)
    b_neg = any(neg in f" {b} " for neg in _NEGATIONS)
    if a_neg == b_neg:
        return False
    words_a = set(w.strip(".,!?;:'\"") for w in a.split())
    words_b = set(w.strip(".,!?;:'\"") for w in b.split())
    words_a.discard("")
    words_b.discard("")
    overlap = words_a & words_b
    # Require at least 2 meaningful shared words so "uses vim" vs
    # "does not use a vim plugin" doesn't read as a contradiction.
    return len(overlap) >= 2


__all__ = ["run_consolidation", "default_llm"]
