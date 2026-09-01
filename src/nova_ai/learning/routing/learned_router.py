"""Learned router policy — trace-driven query_class -> model mapping.

Merges the runtime ``select_model()`` logic from ``TraceDrivenPolicy``
with the batch ``update()`` logic from ``SFTRouterPolicy`` into a single
class registered as ``"learned"`` in ``RouterPolicyRegistry``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from nova_ai.core.registry import RouterPolicyRegistry
from nova_ai.core.types import RoutingContext
from nova_ai.learning._stubs import RouterPolicy
from nova_ai.learning.routing._utils import classify_query

logger = logging.getLogger(__name__)


class LearnedRouterPolicy(RouterPolicy):
    """Trace-driven router that learns query_class -> model mappings.

    Implements ``RouterPolicy.select_model()`` for runtime routing AND
    provides ``update_from_traces()`` / ``observe()`` for learning from traces,
    plus ``update()`` for batch learning from a trace store.
    """

    def __init__(
        self,
        analyzer: Optional[Any] = None,
        *,
        available_models: Optional[List[str]] = None,
        default_model: str = "",
        fallback_model: str = "",
        policy_path: Optional[Any] = None,
    ) -> None:
        self._analyzer = analyzer
        self._available = available_models or []
        self._default = default_model
        self._fallback = fallback_model
        self._policy_map: Dict[str, str] = {}
        self._confidence: Dict[str, int] = {}
        self.min_samples: int = 5
        # Optional persistence: when set, the policy map is loaded at init
        # (confidence pre-satisfied so learned entries actually apply) and
        # can be written back with save().
        self.policy_path = Path(policy_path) if policy_path else None
        if self.policy_path is not None:
            self.load()

    def save(self) -> Optional[Path]:
        """Persist the policy map as ``{qclass: {"model": ..., "confidence": ...}}``.

        Returns the written path, or ``None`` when no ``policy_path`` is set.
        """
        if self.policy_path is None:
            return None
        payload = {
            qclass: {"model": model, "confidence": self._confidence.get(qclass, 0)}
            for qclass, model in self._policy_map.items()
        }
        self.policy_path.parent.mkdir(parents=True, exist_ok=True)
        self.policy_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return self.policy_path

    def load(self) -> bool:
        """Load a previously saved policy map. True when anything loaded."""
        if self.policy_path is None or not self.policy_path.exists():
            return False
        try:
            payload = json.loads(self.policy_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read learned policy at %s: %s",
                           self.policy_path, exc)
            return False
        if not isinstance(payload, dict):
            return False
        for qclass, entry in payload.items():
            if isinstance(entry, dict) and entry.get("model"):
                self._policy_map[qclass] = entry["model"]
                # Persisted entries are proven decisions: pre-satisfy the
                # confidence gate so select_model() actually applies them.
                self._confidence[qclass] = max(
                    int(entry.get("confidence") or 0), self.min_samples
                )
            elif isinstance(entry, str) and entry:
                self._policy_map[qclass] = entry
                self._confidence[qclass] = self.min_samples
        return True

    @property
    def policy_map(self) -> Dict[str, str]:
        """Current learned routing decisions (read-only copy)."""
        return dict(self._policy_map)

    def select_model(self, context: RoutingContext) -> str:
        """Select the best model based on learned policy or fallback."""
        query_class = classify_query(context.query)

        if (
            query_class in self._policy_map
            and self._confidence.get(query_class, 0) >= self.min_samples
        ):
            model = self._policy_map[query_class]
            if not self._available or model in self._available:
                return model

        avail = self._available
        if self._default and (not avail or self._default in avail):
            return self._default
        if self._fallback and (not avail or self._fallback in avail):
            return self._fallback
        if self._available:
            return self._available[0]
        return self._default or ""

    def update_from_traces(
        self,
        *,
        since: Optional[float] = None,
        until: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Recompute the policy map from trace history via TraceAnalyzer."""
        if self._analyzer is None:
            return {"error": "no analyzer configured"}

        traces = self._analyzer._store.list_traces(
            since=since, until=until, limit=10_000
        )
        if not traces:
            return {"updated": False, "reason": "no traces"}

        groups: Dict[str, list] = {}
        for t in traces:
            qclass = classify_query(t.query)
            groups.setdefault(qclass, []).append(t)

        old_map = dict(self._policy_map)
        changes: Dict[str, Dict[str, str]] = {}

        for qclass, class_traces in groups.items():
            model_scores: Dict[str, _ModelScore] = {}
            for t in class_traces:
                if not t.model:
                    continue
                if t.model not in model_scores:
                    model_scores[t.model] = _ModelScore()
                score = model_scores[t.model]
                score.count += 1
                score.total_latency += t.total_latency_seconds
                if t.outcome == "success":
                    score.successes += 1
                if t.feedback is not None:
                    score.feedback_sum += t.feedback
                    score.feedback_count += 1

            if not model_scores:
                continue

            best_model = max(
                model_scores.items(),
                key=lambda kv: kv[1].composite_score(),
            )[0]

            self._policy_map[qclass] = best_model
            self._confidence[qclass] = sum(s.count for s in model_scores.values())

            if old_map.get(qclass) != best_model:
                changes[qclass] = {
                    "old": old_map.get(qclass, ""),
                    "new": best_model,
                }

        return {
            "updated": True,
            "query_classes": len(groups),
            "total_traces": len(traces),
            "changes": changes,
        }

    def observe(
        self,
        query: str,
        model: str,
        outcome: Optional[str],
        feedback: Optional[float],
    ) -> None:
        """Record a single observation for online (incremental) updates."""
        qclass = classify_query(query)
        current_count = self._confidence.get(qclass, 0)

        if qclass not in self._policy_map:
            self._policy_map[qclass] = model
            self._confidence[qclass] = 1
            return

        self._confidence[qclass] = current_count + 1

        if outcome == "success" and feedback is not None and feedback > 0.7:
            if current_count < self.min_samples:
                self._policy_map[qclass] = model

    def update(self, trace_store: Any, **kwargs: object) -> Dict[str, Any]:
        """Batch update: analyze trace outcomes and update the policy map.

        This is the batch learning interface (from the old SFTRouterPolicy).
        """
        try:
            traces = trace_store.list_traces()
        except Exception as exc:
            logger.warning("Learned router update failed: %s", exc)
            return {"updated": False, "reason": "Could not access trace store"}

        class_model_scores: Dict[str, Dict[str, List[float]]] = {}
        for trace in traces:
            query_class = classify_query(trace.query)
            model = trace.model or "unknown"
            outcome_score = 1.0 if trace.outcome == "success" else 0.0
            fb = trace.feedback if trace.feedback is not None else 0.5
            composite = 0.6 * outcome_score + 0.4 * fb

            if query_class not in class_model_scores:
                class_model_scores[query_class] = {}
            if model not in class_model_scores[query_class]:
                class_model_scores[query_class][model] = []
            class_model_scores[query_class][model].append(composite)

        changes = {}
        for qclass, model_scores in class_model_scores.items():
            best_model = None
            best_score = -1.0
            for model, scores in model_scores.items():
                if len(scores) >= self.min_samples:
                    avg = sum(scores) / len(scores)
                    if avg > best_score:
                        best_score = avg
                        best_model = model
            if best_model and best_model != self._policy_map.get(qclass):
                self._policy_map[qclass] = best_model
                changes[qclass] = best_model

        return {
            "updated": bool(changes),
            "changes": changes,
            "policy_map": dict(self._policy_map),
        }


class _ModelScore:
    """Accumulator for per-model scoring during policy update."""

    __slots__ = (
        "count",
        "successes",
        "total_latency",
        "feedback_sum",
        "feedback_count",
    )

    def __init__(self) -> None:
        self.count = 0
        self.successes = 0
        self.total_latency = 0.0
        self.feedback_sum = 0.0
        self.feedback_count = 0

    def composite_score(self) -> float:
        """Weighted score combining success rate and feedback."""
        sr = self.successes / self.count if self.count else 0.0
        fb = self.feedback_sum / self.feedback_count if self.feedback_count else 0.5
        return 0.6 * sr + 0.4 * fb


def ensure_registered() -> None:
    """Register LearnedRouterPolicy if not already present."""
    if not RouterPolicyRegistry.contains("learned"):
        RouterPolicyRegistry.register_value("learned", LearnedRouterPolicy)


ensure_registered()

__all__ = ["LearnedRouterPolicy", "ensure_registered"]
