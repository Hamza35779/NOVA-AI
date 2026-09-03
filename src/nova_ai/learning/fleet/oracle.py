"""Fleet Oracle — query the pooled fleet dataset locally.

Deliberately simple and explainable: keyword-bucketed aggregation over
the anonymized reports. No LLM, no embeddings — just group reports by a
hardware bucket (GPU VRAM ranges), pick the winner per bucket per metric,
and render a table. The question is scanned for:

* VRAM hints ("8gb", "24 gb", "4090" -> known-card lookup)
* intent keywords ("code", "fast"/"latency", "throughput", "energy"/"efficiency")
* model-name substrings (to show one model's standing)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# Rough VRAM→bucket mapping. Buckets are coarse on purpose: the fleet
# dataset is small and the answer should be stable, not overfit.
VRAM_BUCKETS: List[tuple[str, float, float]] = [
    ("<=8GB", 0.0, 8.0),
    ("9-16GB", 8.0, 16.0),
    ("17-24GB", 16.0, 24.0),
    ("25-48GB", 24.0, 48.0),
    (">48GB", 48.0, float("inf")),
]

# Well-known card names → approximate VRAM (GB), so "4090" resolves even
# when the asker has no card of their own.
KNOWN_CARDS: Dict[str, float] = {
    "3060": 12.0,
    "3070": 8.0,
    "3080": 10.0,
    "3090": 24.0,
    "4060": 8.0,
    "4070": 12.0,
    "4080": 16.0,
    "4090": 24.0,
    "5070": 12.0,
    "5080": 16.0,
    "5090": 32.0,
    "a100": 80.0,
    "h100": 80.0,
    "m2": 16.0,
    "m3": 16.0,
    "m4": 16.0,
}

INTENT_KEYWORDS: Dict[str, tuple[str, ...]] = {
    "code": ("code", "coding", "program", "patch", "review"),
    "latency": ("fast", "latency", "snappy", "responsive", "ttft"),
    "throughput": ("throughput", "tok/s", "tokens per second", "speed"),
    "energy": ("energy", "efficiency", "efficient", "watt", "joule", "power"),
    "cheap": ("cheap", "free", "cost"),
}


@dataclass
class FleetAnswer:
    """Structured result of a fleet query."""

    question: str
    intent: str = "latency"  # metric the winner is chosen by
    bucket_label: str = ""  # hardware bucket filter ("" = all)
    matched_model: str = ""  # model-name substring filter ("" = none)
    reports_used: int = 0
    buckets: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def headline(self) -> str:
        """One-line answer: the winning model in the most relevant bucket."""
        metric = METRIC_FOR_INTENT.get(self.intent, "avg_latency_s")
        for bucket in self.buckets:
            if self.bucket_label and bucket["label"] != self.bucket_label:
                continue
            winners = bucket.get("winners") or {}
            winner = winners.get(metric)
            if winner:
                detail = f"{winner['value']:.1f}"
                unit = {
                    "latency": "s avg latency",
                    "throughput": " tok/s",
                    "energy": " tok/J",
                }.get(self.intent, "")
                return (
                    f"{winner['model']} — {detail}{unit} "
                    f"({bucket['label']}, {winner['call_count']} calls)"
                )
        return "No fleet data matches that question yet."


def vram_bucket(vram_gb: float) -> str:
    """Map a VRAM size to its bucket label."""
    for label, lo, hi in VRAM_BUCKETS:
        if lo < vram_gb <= hi or (lo == 0.0 and vram_gb <= hi):
            return label
    return ">48GB"


def _detect_intent(question: str) -> str:
    q = question.lower()
    if any(kw in q for kw in INTENT_KEYWORDS["energy"]):
        return "energy"
    if any(kw in q for kw in INTENT_KEYWORDS["throughput"]):
        return "throughput"
    if any(kw in q for kw in INTENT_KEYWORDS["code"]):
        # code questions care about quality proxies we don't have; use
        # throughput as the tiebreaker metric but keep the intent label
        return "code"
    return "latency"


METRIC_FOR_INTENT: Dict[str, str] = {
    "latency": "avg_latency_s",
    "code": "avg_throughput_tok_per_sec",
    "throughput": "avg_throughput_tok_per_sec",
    "energy": "avg_tokens_per_joule",
}

LOWER_IS_BETTER = {"avg_latency_s"}


def _detect_vram(question: str) -> Optional[float]:
    """Extract a VRAM hint from the question (explicit GB or a known card)."""
    q = question.lower()
    m = re.search(r"(\d{1,3})\s*gb", q)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    for card, vram in KNOWN_CARDS.items():
        if re.search(rf"\b{re.escape(card)}\b", q):
            return vram
    return None


def _detect_model(question: str, reports: Sequence[Dict[str, Any]]) -> str:
    """If the question names a model that exists in the fleet data, return it.

    Only model ids of a plausible length (>= 3 chars) match — a
    one-character id like ``"a"`` would otherwise match every question
    containing that letter or the English article "a".
    """
    q = question.lower()
    seen: set[str] = set()
    for report in reports:
        for model in report.get("models", []):
            model_id = str(model.get("model_id", ""))
            if not model_id or model_id.lower() in seen:
                continue
            seen.add(model_id.lower())
            if len(model_id) < 3:
                continue
            if re.search(rf"(?<![a-z0-9._-]){re.escape(model_id.lower())}"
                         rf"(?![a-z0-9._-])", q):
                return model_id
    return ""


def query_fleet(
    question: str,
    reports: Sequence[Dict[str, Any]],
) -> FleetAnswer:
    """Answer a fleet question from loaded report dicts.

    Parameters
    ----------
    question :
        Free text, e.g. ``"best 8B model for code on a 4090?"``.
    reports :
        Report dicts as produced by :func:`nova_ai.learning.fleet.report.build_report`
        (loaded via :func:`nova_ai.learning.fleet.push.load_reports`).

    Returns
    -------
    FleetAnswer
        Per-bucket winner tables; ``headline`` is the one-line answer.
    """
    intent = _detect_intent(question)
    vram = _detect_vram(question)
    bucket_label = vram_bucket(vram) if vram is not None else ""
    matched_model = _detect_model(question, reports)

    # Deduplicate by report_id — keep the most recently generated entry.
    by_id: Dict[str, Dict[str, Any]] = {}
    for report in reports:
        rid = str(report.get("report_id", ""))
        prev = by_id.get(rid)
        if prev is None or str(report.get("generated_at", "")) > str(
            prev.get("generated_at", "")
        ):
            by_id[rid] = report

    # Aggregate: (bucket, model) -> summed stats.
    agg: Dict[tuple[str, str], Dict[str, Any]] = {}
    for report in by_id.values():
        hardware = report.get("hardware") or {}
        gpu = hardware.get("gpu") or {}
        bucket = vram_bucket(float(gpu.get("vram_gb") or 0.0))
        for model in report.get("models", []):
            model_id = str(model.get("model_id", ""))
            if not model_id:
                continue
            key = (bucket, model_id)
            entry = agg.setdefault(
                key,
                {
                    "call_count": 0,
                    "latency_weighted": 0.0,
                    "throughput_weighted": 0.0,
                    "tpj_weighted": 0.0,
                    "machines": set(),
                },
            )
            calls = int(model.get("call_count", 0))
            entry["call_count"] += calls
            entry["machines"].add(str(report.get("report_id", "")))
            entry["latency_weighted"] += float(model.get("avg_latency_s", 0.0)) * calls
            entry["throughput_weighted"] += (
                float(model.get("avg_throughput_tok_per_sec", 0.0)) * calls
            )
            entry["tpj_weighted"] += (
                float(model.get("avg_tokens_per_joule", 0.0)) * calls
            )

    # Winners per bucket for each metric.
    buckets_out: List[Dict[str, Any]] = []
    for label, _lo, _hi in VRAM_BUCKETS:
        rows = [
            {
                "model": model_id,
                "bucket": b,
                "call_count": e["call_count"],
                "machines": len(e["machines"]),
                "avg_latency_s": e["latency_weighted"] / e["call_count"],
                "avg_throughput_tok_per_sec": (
                    e["throughput_weighted"] / e["call_count"]
                ),
                "avg_tokens_per_joule": e["tpj_weighted"] / e["call_count"],
            }
            for (b, model_id), e in agg.items()
            if e["call_count"] > 0 and b == label
        ]
        if matched_model:
            rows = [r for r in rows if r["model"] == matched_model]

        winners: Dict[str, Dict[str, Any]] = {}
        for metric_name in ("avg_latency_s", "avg_throughput_tok_per_sec",
                            "avg_tokens_per_joule"):
            if not rows:
                continue
            best = min(rows, key=lambda r: r[metric_name]) if (
                metric_name in LOWER_IS_BETTER
            ) else max(rows, key=lambda r: r[metric_name])
            winners[metric_name] = {
                "model": best["model"],
                "value": best[metric_name],
                "call_count": best["call_count"],
            }

        if rows:
            buckets_out.append(
                {
                    "label": label,
                    "rows": rows,
                    "winners": winners,
                }
            )

    return FleetAnswer(
        question=question,
        intent=intent,
        bucket_label=bucket_label,
        matched_model=matched_model,
        reports_used=len(by_id),
        buckets=buckets_out,
    )


__all__ = [
    "FleetAnswer",
    "KNOWN_CARDS",
    "METRIC_FOR_INTENT",
    "VRAM_BUCKETS",
    "query_fleet",
    "vram_bucket",
]
