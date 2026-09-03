"""TrainingDataMiner — extract supervised training pairs from the TraceStore.

Provides three extraction modes:

* **SFT pairs** — (input, output) pairs from high-quality traces for
  supervised fine-tuning.
* **Routing pairs** — per-query-class statistics identifying the best
  model for each class.
* **Agent config pairs** — per-query-class statistics identifying the
  best agent and tool combination.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from nova_ai.core.types import StepType, Trace
from nova_ai.learning.routing._utils import classify_query


class TrainingDataMiner:
    """Extract supervised training pairs from stored traces.

    Parameters
    ----------
    trace_store:
        Any object with a ``list_traces(limit=...)`` method returning
        ``List[Trace]`` (typically a :class:`TraceStore`).
    min_quality:
        Minimum ``feedback`` score for a trace to be included.
    min_samples_per_class:
        Minimum number of samples a query class must have to appear in
        routing/agent-config results.
    """

    def __init__(
        self,
        trace_store: Any,
        *,
        min_quality: float = 0.7,
        min_samples_per_class: int = 1,
    ) -> None:
        self._store = trace_store
        self._min_quality = min_quality
        self._min_samples_per_class = min_samples_per_class

    # -- helpers ----------------------------------------------------------------

    def _quality_traces(self, *, agent: str | None = None) -> List[Trace]:
        """Return traces whose feedback meets the quality threshold."""
        kwargs: Dict[str, Any] = {"limit": 10000}
        if agent is not None:
            kwargs["agent"] = agent
        all_traces = self._store.list_traces(**kwargs)
        return [
            t
            for t in all_traces
            if t.feedback is not None
            and t.feedback >= self._min_quality
            and t.outcome == "success"
        ]

    @staticmethod
    def _tools_from_trace(trace: Trace) -> List[str]:
        """Extract tool names from TOOL_CALL steps in a trace."""
        tools: List[str] = []
        for step in trace.steps:
            if step.step_type == StepType.TOOL_CALL:
                tool_name = step.input.get("tool")
                if tool_name:
                    tools.append(tool_name)
        return tools

    # -- public API -------------------------------------------------------------

    def extract_sft_pairs(self, *, agent: str | None = None) -> List[Dict[str, Any]]:
        """Return SFT training pairs from high-quality traces.

        Each entry is a dict with keys: ``input``, ``output``,
        ``query_class``, ``model``, ``feedback``.

        Duplicate ``(input, output)`` pairs are collapsed; the first
        occurrence is kept.
        """
        traces = self._quality_traces(agent=agent)
        seen: set[tuple[str, str]] = set()
        pairs: List[Dict[str, Any]] = []

        for t in traces:
            key = (t.query, t.result)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(
                {
                    "input": t.query,
                    "output": t.result,
                    "query_class": classify_query(t.query),
                    "model": t.model,
                    "feedback": t.feedback,
                }
            )

        return pairs

    def extract_routing_pairs(
        self, *, agent: str | None = None
    ) -> Dict[str, Dict[str, Any]]:
        """Return per-query-class routing recommendations.

        Returns a dict mapping query class to:

        * ``best_model`` — model with highest average feedback for the class.
        * ``avg_feedback`` — average feedback across all models for the class.
        * ``sample_count`` — total number of qualifying traces in the class.
        * ``all_models`` — dict of ``{model: {"avg_feedback": float, "count": int}}``.
        """
        traces = self._quality_traces(agent=agent)

        # Accumulate per (query_class, model) feedback scores
        class_model_scores: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for t in traces:
            qc = classify_query(t.query)
            class_model_scores[qc][t.model].append(t.feedback)  # type: ignore[arg-type]

        result: Dict[str, Dict[str, Any]] = {}
        for qc, model_scores in class_model_scores.items():
            total_count = sum(len(scores) for scores in model_scores.values())
            if total_count < self._min_samples_per_class:
                continue

            all_models: Dict[str, Dict[str, Any]] = {}
            best_model = ""
            best_avg = -1.0

            for model, scores in model_scores.items():
                avg = sum(scores) / len(scores)
                all_models[model] = {"avg_feedback": avg, "count": len(scores)}
                if avg > best_avg:
                    best_avg = avg
                    best_model = model

            total_scores = [s for scores in model_scores.values() for s in scores]
            overall_avg = sum(total_scores) / len(total_scores) if total_scores else 0.0

            result[qc] = {
                "best_model": best_model,
                "avg_feedback": overall_avg,
                "sample_count": total_count,
                "all_models": all_models,
            }

        return result

    def extract_agent_config_pairs(
        self, *, agent: str | None = None
    ) -> Dict[str, Dict[str, Any]]:
        """Return per-query-class agent and tool recommendations.

        Returns a dict mapping query class to:

        * ``best_agent`` — agent with the highest average feedback.
        * ``best_tools`` — most frequently used tools by the best agent.
        * ``avg_feedback`` — average feedback across all agents for the class.
        * ``sample_count`` — total number of qualifying traces in the class.
        """
        traces = self._quality_traces(agent=agent)

        # Accumulate per (query_class, agent) feedback and tools
        class_agent_scores: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        class_agent_tools: Dict[str, Dict[str, List[List[str]]]] = defaultdict(
            lambda: defaultdict(list)
        )

        for t in traces:
            qc = classify_query(t.query)
            class_agent_scores[qc][t.agent].append(t.feedback)  # type: ignore[arg-type]
            tools = self._tools_from_trace(t)
            class_agent_tools[qc][t.agent].append(tools)

        result: Dict[str, Dict[str, Any]] = {}
        for qc, agent_scores in class_agent_scores.items():
            total_count = sum(len(scores) for scores in agent_scores.values())
            if total_count < self._min_samples_per_class:
                continue

            best_agent = ""
            best_avg = -1.0
            for agent, scores in agent_scores.items():
                avg = sum(scores) / len(scores)
                if avg > best_avg:
                    best_avg = avg
                    best_agent = agent

            # Collect tool frequency for best agent
            tool_freq: Dict[str, int] = defaultdict(int)
            for tool_list in class_agent_tools[qc].get(best_agent, []):
                for tool in tool_list:
                    tool_freq[tool] += 1

            best_tools = sorted(tool_freq, key=tool_freq.get, reverse=True)  # type: ignore[arg-type]

            total_scores = [s for scores in agent_scores.values() for s in scores]
            overall_avg = sum(total_scores) / len(total_scores) if total_scores else 0.0

            result[qc] = {
                "best_agent": best_agent,
                "best_tools": best_tools,
                "avg_feedback": overall_avg,
                "sample_count": total_count,
            }

        return result


def extract_preference_pairs(
    conv_store: Any,
    *,
    trace_store: Any = None,
    min_quality: float = 0.7,
) -> List[Dict[str, Any]]:
    """Build DPO preference pairs from conversation forks + trace signals.

    Three sources, in priority order:

    1. **Recorded pairs** (``conv_store.list_preference_pairs()``) — the
       fork/regen/race picks made in the app or via ``nova conversation
       pick``. Chosen vs rejected sibling answers on the same prompt.
    2. **Regen signal from traces** — the same query asked twice with
       feedback improving (the later, higher-scored answer is chosen).
    3. **Thumbs signal from traces** — a low-rated answer followed by a
       later better one on the same query (hash-matched, the
       ``RoutingFeedbackStore.query_hash`` convention).

    Returns a list of ``{prompt, chosen, rejected, source}`` dicts —
    the schema ``DPOTrainer`` consumes.
    """
    pairs: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    # 1. Recorded sibling choices ------------------------------------------------
    try:
        recorded = conv_store.list_preference_pairs(limit=100000)
    except AttributeError:
        recorded = []
    for rec in recorded:
        chosen_node = conv_store.get_node(rec["chosen_id"])
        if chosen_node is None:
            continue
        rejected_nodes = [
            conv_store.get_node(rid)
            for rid in rec["rejected_ids"]
            if conv_store.get_node(rid) is not None
        ]
        prompt_text = "\n".join(
            str(m.get("content", "")) for m in rec["prompt_path"]
        ).strip()
        for rejected in rejected_nodes:
            key = (prompt_text, chosen_node["content"], rejected["content"])
            same_answer = chosen_node["content"] == rejected["content"]
            if (
                key in seen
                or same_answer
                or not chosen_node["content"]
                or not rejected["content"]
            ):
                continue
            seen.add(key)
            pairs.append(
                {
                    "prompt": prompt_text,
                    "chosen": chosen_node["content"],
                    "rejected": rejected["content"],
                    "source": rec["source"],
                }
            )

    # 2 + 3. Trace-derived signals ------------------------------------------------
    if trace_store is not None:
        pairs.extend(
            _pairs_from_traces(trace_store, min_quality=min_quality, seen=seen)
        )
    return pairs


def _hash_query(content: str) -> str:
    """Query hash matching ``engine/router_learning._query_hash``."""
    import hashlib

    return hashlib.sha256(content.strip().lower().encode("utf-8")).hexdigest()


def _pairs_from_traces(
    trace_store: Any,
    *,
    min_quality: float,
    seen: set[tuple[str, str, str]],
) -> List[Dict[str, Any]]:
    """Regen (feedback improves on repeat) and thumbs (down then better)."""
    try:
        traces = trace_store.list_traces(limit=100000)
    except Exception:
        return []

    by_hash: Dict[str, List[Any]] = defaultdict(list)
    for t in traces:
        qh = _hash_query(t.query or "")
        by_hash[qh].append(t)

    pairs: List[Dict[str, Any]] = []
    for group in by_hash.values():
        if len(group) < 2:
            continue
        # Oldest first so "later" means "more recent attempt".
        group.sort(key=lambda t: getattr(t, "started_at", None) or "")
        for i, worse in enumerate(group):
            if worse.feedback is None:
                continue
            for better in group[i + 1 :]:
                if better.feedback is None:
                    continue
                if better.feedback <= worse.feedback:
                    continue
                if not better.result or not worse.result:
                    continue
                if better.result == worse.result:
                    continue
                key = (worse.query, better.result, worse.result)
                if key in seen:
                    continue
                seen.add(key)
                pairs.append(
                    {
                        "prompt": worse.query,
                        "chosen": better.result,
                        "rejected": worse.result,
                        "source": "regen" if better.feedback >= min_quality else "thumbs",
                    }
                )
                break  # one chosen per rejected answer
    return pairs


__all__ = ["TrainingDataMiner", "extract_preference_pairs"]
