"""Model racing — generate sibling answers, judge, record the preference.

``race_models`` is the conversation-level entry point for "fork the
conversation, race two models, keep the winner": for each model in
``models`` it generates an assistant answer under the same prompt node,
auto-judges the outputs (first-line YES/NO convention, same as the
proving ground and the gauntlet), and records the winner as a
preference pair for the DPO lane.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from nova_ai.conversations.store import ConversationStore

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM = (
    "You are a strict, impartial judge. Compare two assistant answers to "
    "the same conversation and decide which is better. Reply with YES on "
    "the first line if the FIRST answer is better, NO if the SECOND is "
    "better, then one short sentence of reasoning."
)


def _extract_content(response: Any) -> str:
    """Pull the text out of an engine ``generate()`` dict (or a raw string)."""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        content = response.get("content")
        if isinstance(content, str):
            return content
        message = response.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
    return ""


def _judge_answer(
    judge: Any,
    prompt_path: Sequence[dict[str, Any]],
    answer_a: str,
    answer_b: str,
    judge_model: str = "",
) -> str:
    """Return ``"a"`` or ``"b"`` from the judge's first-line YES/NO verdict.

    Yes → the first (older) answer wins. Any exception or unparseable
    verdict defaults to ``"a"`` — a tie-break is better than a crash.
    """
    convo = "\n".join(
        f"{m.get('role', 'user')}: {m.get('content', '')}" for m in prompt_path
    )
    prompt = (
        f"Conversation so far:\n{convo}\n\n"
        f"--- ANSWER A ---\n{answer_a}\n\n"
        f"--- ANSWER B ---\n{answer_b}\n\n"
        "Which answer is better? First line: YES for A or NO for B."
    )
    try:
        text = judge.generate(prompt, model=judge_model, system=_JUDGE_SYSTEM)
    except Exception as exc:
        logger.warning("race judge failed (%s); defaulting to first answer", exc)
        return "a"
    return "a" if text.strip().upper().startswith("YES") else "b"


def race_models(
    *,
    store: ConversationStore,
    parent_node_id: str,
    models: Sequence[str],
    engine: Any,
    judge: Optional[Any] = None,
    judge_model: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """Generate sibling answers for each model and keep the winner.

    Parameters
    ----------
    store :
        The conversation tree store.
    parent_node_id :
        The prompt node the answers answer (a user message node).
    models :
        Model identifiers, one sibling answer each.
    engine :
        An ``InferenceEngine`` with ``generate(messages, model=...)``.
    judge :
        Optional judge with ``generate(prompt, model=, system=)`` (the
        ``NovaDirectBackend`` / ``LLMJudgeScorer`` seam). ``None`` keeps
        the *first* model's answer (no auto-judging).

    Returns
    -------
    dict
        ``{candidates: [{model, node_id, content}], winner_node_id,
        winner_model, pair_id}``.
    """
    parent = store.get_node(parent_node_id)
    if parent is None:
        raise ValueError(f"unknown parent node: {parent_node_id}")

    prompt_path = store.path_to_root(parent_node_id)
    # The prompt node itself is the last user turn; the judge sees the
    # path without the root system marker.
    prompt_path = [m for m in prompt_path if m["role"] != "system"]

    from nova_ai.core.types import Message, Role

    candidates: list[dict[str, Any]] = []
    for model in models:
        messages = [
            Message(role=Role(m["role"]), content=m.get("content", ""))
            for m in prompt_path
        ]
        try:
            response = engine.generate(
                messages, model=model, temperature=temperature, max_tokens=max_tokens
            )
            content = _extract_content(response)
            success = bool(content)
        except Exception as exc:
            logger.warning("race: model %s generation failed: %s", model, exc)
            content, success = f"[generation failed: {exc}]", False
        node_id = store.add_message(
            parent["conversation_id"],
            parent_node_id,
            "assistant",
            content,
            model=model,
            engine=getattr(engine, "engine_id", ""),
            metadata={"race": True, "success": success},
        )
        candidates.append(
            {"model": model, "node_id": node_id, "content": content}
        )

    if not candidates:
        raise ValueError("race_models requires at least one model")

    if judge is not None and len(candidates) > 1 and candidates[0]["content"]:
        verdict = _judge_answer(
            judge,
            prompt_path,
            candidates[0]["content"],
            candidates[1]["content"],
            judge_model=judge_model,
        )
        if verdict == "b":
            candidates = [candidates[1], candidates[0]]
    # Without a judge (or with a single model) the first answer wins.

    winner = candidates[0]
    losers = [c for c in candidates if c["node_id"] != winner["node_id"]]
    pair_id = store.add_sibling_choice(
        parent["conversation_id"],
        prompt_path,
        winner["node_id"],
        [c["node_id"] for c in losers],
        source="race",
    )
    return {
        "candidates": candidates,
        "winner_node_id": winner["node_id"],
        "winner_model": winner["model"],
        "pair_id": pair_id,
    }


__all__ = ["race_models"]
