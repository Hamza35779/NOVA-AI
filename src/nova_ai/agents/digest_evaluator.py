"""Digest quality evaluator for the Morning Digest agent.

Used by :meth:`~nova_ai.agents.morning_digest.MorningDigestAgent.run` to
self-evaluate a synthesized briefing against the digest rubric and produce
actionable feedback for a regeneration pass. ``evaluate`` returns a
``(score, feedback)`` tuple; any failure inside it is caught by the caller's
``soft_fail`` so an evaluator problem can never block digest delivery.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from nova_ai.core.types import Message, Role
from nova_ai.core.utils import soft_fail

# Threshold below which morning_digest.py regenerates the briefing.
PASSING_SCORE = 7.0

_EVALUATION_PROMPT = """You are a strict quality reviewer for a spoken morning-briefing agent.

Given the RAW COLLECTED DATA and the DRAFT BRIEFING, score the briefing 0-10
and list concrete problems. Judge it against these rules:

1. PRIORITY ORDER - the most attention-worthy items come first (overdue
   tasks, deadlines, events needing preparation), not chronologically.
2. NO RAW NUMBERS - health must be interpreted ("your sleep was solid"),
   never enumerated (no HRV 53, no "82 readiness", no step counts).
3. NO HALLUCINATION - every claim must be traceable to the data.
4. NO DISCONNECTED SOURCES - never mention sources that returned no data.
5. TRIAGE - messages from real people needing replies rank above automated
   mail; newsletters/marketing are skipped entirely.
6. STYLE - 2-4 minutes spoken (200-250 words), no markdown, no bullets,
   no emojis, no headers.

Respond in EXACTLY this format:

SCORE: <single number 0-10>
FEEDBACK: <one or two sentences of the most important fixes; "none" if the
briefing is good>
"""


class DigestEvaluator:
    """LLM-based rubric evaluator for digest drafts."""

    def __init__(self, engine: Any, model: str) -> None:
        self._engine = engine
        self._model = model

    # ------------------------------------------------------------------
    # Score parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_score(text: str) -> float:
        """Extract the 0-10 score from an evaluator response.

        Looks for the ``SCORE:`` line first, then any bare number in the
        first line as a fallback. Returns 0.0 when nothing parseable is
        found (the caller treats 0.0 + empty feedback as a no-op).
        """
        match = re.search(r"SCORE\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
        if match:
            return max(0.0, min(10.0, float(match.group(1))))
        first_line = text.strip().splitlines()[0] if text.strip() else ""
        fallback = re.search(r"\b([0-9](?:\.[0-9])?|10)\b", first_line)
        return max(0.0, min(10.0, float(fallback.group(1)))) if fallback else 0.0

    @staticmethod
    def _parse_feedback(text: str) -> str:
        match = re.search(r"FEEDBACK\s*[:=]\s*(.+)", text, re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        feedback = " ".join(match.group(1).split()).strip()
        if feedback.lower() in {"", "none", "n/a", "no issues", "no feedback"}:
            return ""
        return feedback[:600]

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        collected_data: str,
        narrative: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> tuple[float, str]:
        """Score *narrative* against *collected_data*.

        Returns ``(score, feedback)``. On any engine failure the score is
        0.0 with empty feedback — combined with the caller's "only
        regenerate when there is feedback" check, a failed evaluation never
        triggers a spurious regeneration.
        """
        messages = [
            Message(role=Role.SYSTEM, content=_EVALUATION_PROMPT),
            Message(
                role=Role.USER,
                content=(
                    f"RAW COLLECTED DATA:\n{collected_data[:8000]}\n\n"
                    f"DRAFT BRIEFING:\n{narrative[:4000]}\n\n"
                    "Score it. Format: SCORE: <n> then FEEDBACK: <text>"
                ),
            ),
        ]
        try:
            result = self._engine.generate(
                messages,
                model=self._model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            soft_fail(
                logging.getLogger(__name__),
                exc,
                "Evaluator generate() failed",
            )
            return 0.0, ""

        content = result.get("content", "") if isinstance(result, dict) else str(result)
        content = self._strip_think(content)
        return self._parse_score(content), self._parse_feedback(content)

    @staticmethod
    def _strip_think(text: str) -> str:
        """Drop <think> blocks some local reasoning models emit."""
        return re.sub(
            r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE
        ).strip()


__all__ = ["DigestEvaluator", "PASSING_SCORE"]
