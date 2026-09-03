"""Mine repeated tool-call sequences from traces — the raw ore of the forge.

``PatternMiner`` walks ``Trace.steps`` for ``StepType.TOOL_CALL`` entries
(the collector records ``input.tool``/``input.arguments`` and
``output.success`` — see ``traces/collector.py``), groups traces by their
ordered tool sequence, and returns candidates worth synthesizing: the same
sequence seen at least ``min_pattern_count`` times with average feedback
above ``min_feedback``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Optional

from nova_ai.core.types import StepType

logger = logging.getLogger(__name__)


def _tool_sequence(trace: Any) -> list[dict[str, Any]]:
    """Extract ordered tool-call records from a trace."""
    calls: list[dict[str, Any]] = []
    for step in getattr(trace, "steps", None) or []:
        if getattr(step, "step_type", None) != StepType.TOOL_CALL:
            continue
        inp = getattr(step, "input", None) or {}
        out = getattr(step, "output", None) or {}
        tool = inp.get("tool", "")
        if not tool:
            continue
        calls.append(
            {
                "tool": tool,
                "arguments": inp.get("arguments", {}) or {},
                "success": bool(out.get("success", False)),
                "result": out.get("result", ""),
            }
        )
    return calls


class PatternMiner:
    """Find repeated tool-call sequences across traces."""

    def __init__(
        self,
        trace_store: Any,
        *,
        min_pattern_count: int = 3,
        min_feedback: float = 0.7,
    ) -> None:
        self._store = trace_store
        self._min_count = max(1, min_pattern_count)
        self._min_feedback = min_feedback

    def mine(
        self,
        *,
        since: Optional[float] = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return patterns: ``{sequence, count, avg_feedback, successes,
        example_trace_ids, examples}``.

        ``sequence`` is a list of tool names in call order; ``examples``
        keeps up to 3 concrete ``(query, tool, arguments, result)`` records
        per pattern so the synthesizer has worked instances to learn from.
        Sorted by count (descending) then avg feedback.
        """
        try:
            traces = self._store.list_traces(since=since, limit=limit)
        except Exception as exc:
            logger.warning("PatternMiner could not list traces: %s", exc)
            return []

        groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for trace in traces:
            calls = _tool_sequence(trace)
            if len(calls) < 2:
                continue  # single-tool traces are not skill-shaped
            seq = tuple(c["tool"] for c in calls)
            feedback = getattr(trace, "feedback", None)
            groups[seq].append(
                {
                    "trace_id": getattr(trace, "trace_id", ""),
                    "query": getattr(trace, "query", ""),
                    "feedback": float(feedback) if feedback is not None else None,
                    "calls": calls,
                }
            )

        candidates: list[dict[str, Any]] = []
        for seq, members in groups.items():
            feedbacks = [m["feedback"] for m in members if m["feedback"] is not None]
            avg_feedback = (
                sum(feedbacks) / len(feedbacks) if feedbacks else 0.0
            )
            successes = sum(1 for m in members if all(c["success"] for c in m["calls"]))
            if len(members) < self._min_count:
                continue
            if feedbacks and avg_feedback < self._min_feedback:
                continue
            candidates.append(
                {
                    "sequence": list(seq),
                    "count": len(members),
                    "avg_feedback": round(avg_feedback, 3),
                    "successes": successes,
                    "example_trace_ids": [m["trace_id"] for m in members[:3]],
                    "examples": [
                        {
                            "query": m["query"],
                            "arguments": m["calls"][0]["arguments"],
                            "calls": m["calls"][:3],
                        }
                        for m in members[:3]
                    ],
                }
            )

        candidates.sort(key=lambda c: (c["count"], c["avg_feedback"]), reverse=True)
        return candidates


__all__ = ["PatternMiner"]
