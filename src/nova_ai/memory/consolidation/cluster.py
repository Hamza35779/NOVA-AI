"""Cluster episodic traces into consolidation-ready groups.

The miner groups recent traces two ways: by query class (cheap, always
available) and by embedding similarity within each class (when an
embedder is available). Clusters smaller than the configured
``min_session_messages`` are dropped — one-off conversations are noise,
patterns are signal.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from nova_ai.learning.routing._utils import classify_query

logger = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors (no numpy)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class SessionMiner:
    """Group recent traces into clusters of related conversations."""

    def __init__(
        self,
        trace_store: Any,
        *,
        embedder: Optional[Any] = None,
        similarity_threshold: float = 0.75,
    ) -> None:
        """
        Parameters
        ----------
        trace_store:
            Object exposing ``list_traces(**filters)`` (``TraceStore``).
        embedder:
            Optional object with ``embed(texts) -> vectors``. When ``None``,
            clustering falls back to query-class grouping only. Inject a
            fake in tests.
        """
        self._store = trace_store
        self._embedder = embedder
        self._similarity_threshold = similarity_threshold

    # -- public API ----------------------------------------------------------

    def mine(
        self,
        *,
        since: Optional[float] = None,
        min_cluster_size: int = 6,
    ) -> list[dict[str, Any]]:
        """Return clusters: ``{topic_hint, messages, trace_ids}``.

        ``messages`` is a list of ``{"role", "content", "feedback"}`` dicts
        (one per trace: the query plus the assistant's answer), and
        ``trace_ids`` preserves the source-trace provenance.
        """
        traces = self._store.list_traces(since=since, limit=500)
        if not traces:
            return []

        buckets: dict[str, list[Any]] = {}
        for trace in traces:
            qclass = classify_query(trace.query or "")
            buckets.setdefault(qclass, []).append(trace)

        clusters: list[dict[str, Any]] = []
        for qclass, group in buckets.items():
            if self._embedder is not None:
                clusters.extend(
                    self._cluster_embedded(qclass, group, min_cluster_size)
                )
            else:
                if len(group) >= min_cluster_size:
                    clusters.append(self._make_cluster(qclass, group))
        return clusters

    # -- internals -----------------------------------------------------------

    def _make_cluster(
        self, topic_hint: str, traces: Iterable[Any]
    ) -> dict[str, Any]:
        traces = list(traces)
        messages = [
            {
                "role": "user",
                "content": t.query or "",
                "feedback": t.feedback,
            }
            for t in traces
        ]
        messages += [
            {
                "role": "assistant",
                "content": t.result or "",
                "feedback": t.feedback,
            }
            for t in traces
        ]
        return {
            "topic_hint": topic_hint,
            "messages": messages,
            "trace_ids": [t.trace_id for t in traces],
        }

    def _cluster_embedded(
        self,
        qclass: str,
        traces: list[Any],
        min_cluster_size: int,
    ) -> list[dict[str, Any]]:
        """Greedy centroid clustering of queries within a query class."""
        queries = [t.query or "" for t in traces]
        try:
            vectors = [list(v) for v in self._embedder.embed(queries)]
        except Exception as exc:  # embedder failure must not break mining
            logger.debug("Embedder failed (%s); falling back to class bucket", exc)
            if len(traces) >= min_cluster_size:
                return [self._make_cluster(qclass, traces)]
            return []

        assigned: list[Optional[int]] = [None] * len(traces)
        centroids: list[list[float]] = []
        groups: list[list[int]] = []

        for i, vec in enumerate(vectors):
            best_idx: Optional[int] = None
            best_score = self._similarity_threshold
            for ci, centroid in enumerate(centroids):
                score = _cosine(vec, centroid)
                if score >= best_score:
                    best_score = score
                    best_idx = ci
            if best_idx is None:
                centroids.append(list(vec))
                groups.append([i])
            else:
                groups[best_idx].append(i)
                # Update the centroid to the running mean.
                members = groups[best_idx]
                dim = len(centroids[best_idx])
                centroids[best_idx] = [
                    sum(vectors[m][d] for m in members) / len(members)
                    for d in range(dim)
                ]
            assigned[i] = best_idx

        clusters: list[dict[str, Any]] = []
        for group in groups:
            if len(group) < min_cluster_size:
                continue
            member_traces = [traces[i] for i in group]
            clusters.append(self._make_cluster(qclass, member_traces))
        return clusters


__all__ = ["SessionMiner"]
