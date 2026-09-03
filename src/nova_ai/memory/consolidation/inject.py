"""Core-memory injection — serve distilled facts inside every query.

``core_memory_block`` renders the active fact base as a compact
markdown block. :meth:`inject` prepends it to a message list; every
failure mode degrades to "keep the conversation as it was" — a broken
fact base can never break answering.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

_HEADER = "## What NOVA knows about you"


def core_memory_block(fact_store: Any, *, max_chars: int = 4000) -> str:
    """Render active facts as a compact markdown block ("" when empty)."""
    try:
        facts = fact_store.export_core(max_chars=max_chars)
    except Exception as exc:
        logger.debug("Fact store export failed: %s", exc)
        return ""
    if not facts:
        return ""
    lines = [_HEADER, ""]
    for fact in facts:
        lines.append(f"- {fact['content']}")
    return "\n".join(lines)


def inject(
    messages: List[Any],
    fact_store: Optional[Any],
    *,
    max_chars: int = 4000,
) -> List[Any]:
    """Prepend the core-memory block as a system message.

    Returns a **new** list; the input is never mutated. When the store is
    ``None``, the block is empty, or anything raises, the original list
    is returned unchanged.
    """
    if fact_store is None:
        return messages
    try:
        block = core_memory_block(fact_store, max_chars=max_chars)
    except Exception as exc:
        logger.debug("Core-memory injection skipped: %s", exc)
        return messages
    if not block:
        return messages

    from nova_ai.core.types import Message, Role

    return [Message(role=Role.SYSTEM, content=block), *messages]


__all__ = ["core_memory_block", "inject"]
