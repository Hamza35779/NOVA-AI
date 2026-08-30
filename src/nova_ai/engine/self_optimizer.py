"""Self-Optimization Engine — adaptive performance tracking, auto-tuning, and feedback loops.

Tracks every tool execution and model inference, learns from outcomes,
and progressively tunes internal parameters to maximize accuracy and speed.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from nova_ai.core.paths import get_config_dir

logger = logging.getLogger(__name__)

_METRICS_FILE = "optimizer_metrics.json"
_TUNING_FILE = "optimizer_tuning.json"


@dataclass(slots=True)
class ExecutionRecord:
    """Single execution trace for a tool or model call."""

    component: str
    action: str
    duration_ms: float
    success: bool
    input_size: int = 0
    output_size: int = 0
    error: str = ""
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ComponentProfile:
    """Aggregated performance profile for a single component."""

    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    total_duration_ms: float = 0.0
    avg_duration_ms: float = 0.0
    p95_duration_ms: float = 0.0
    success_rate: float = 1.0
    recent_durations: List[float] = field(default_factory=list)


class SelfOptimizer:
    """Central performance tracker and adaptive optimizer for NOVA AI.

    Capabilities:
    - Records execution traces for every tool and model call
    - Computes rolling statistics (avg, p95, success rate)
    - Detects degradation and triggers auto-tuning
    - Persists metrics across sessions for long-term learning
    - Provides optimization recommendations
    """

    MAX_RECENT_RECORDS = 200
    DEGRADATION_THRESHOLD = 0.7  # success rate below this triggers alert
    SLOWDOWN_FACTOR = 2.5  # if p95 > avg * this, flag as slow

    def __init__(self, persist_dir: Optional[Path] = None) -> None:
        self._persist_dir = persist_dir or (get_config_dir() / "optimizer")
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        self._records: List[ExecutionRecord] = []
        self._profiles: Dict[str, ComponentProfile] = defaultdict(ComponentProfile)
        self._tuning: Dict[str, Any] = {}
        self._callbacks: List[Callable[[ExecutionRecord], None]] = []

        self._load_persisted()

    # ── Recording ──────────────────────────────────────────────

    def record(
        self,
        component: str,
        action: str,
        duration_ms: float,
        success: bool,
        input_size: int = 0,
        output_size: int = 0,
        error: str = "",
        **metadata: Any,
    ) -> None:
        """Record a single execution event and update rolling stats."""
        entry = ExecutionRecord(
            component=component,
            action=action,
            duration_ms=duration_ms,
            success=success,
            input_size=input_size,
            output_size=output_size,
            error=error,
            metadata=metadata,
        )

        with self._lock:
            self._records.append(entry)
            if len(self._records) > self.MAX_RECENT_RECORDS:
                self._records = self._records[-self.MAX_RECENT_RECORDS :]
            self._update_profile(component, entry)

        for cb in self._callbacks:
            try:
                cb(entry)
            except Exception:
                pass

    def _update_profile(self, component: str, entry: ExecutionRecord) -> None:
        """Update the rolling profile for a component. Caller holds lock."""
        profile = self._profiles[component]
        profile.total_calls += 1
        profile.total_duration_ms += entry.duration_ms

        if entry.success:
            profile.successes += 1
        else:
            profile.failures += 1

        profile.success_rate = profile.successes / profile.total_calls
        profile.avg_duration_ms = profile.total_duration_ms / profile.total_calls

        profile.recent_durations.append(entry.duration_ms)
        if len(profile.recent_durations) > 50:
            profile.recent_durations = profile.recent_durations[-50:]

        if len(profile.recent_durations) >= 5:
            sorted_d = sorted(profile.recent_durations)
            idx = int(len(sorted_d) * 0.95)
            profile.p95_duration_ms = sorted_d[min(idx, len(sorted_d) - 1)]

    # ── Querying ───────────────────────────────────────────────

    def get_profile(self, component: str) -> Dict[str, Any]:
        """Get performance profile for a specific component."""
        with self._lock:
            if component not in self._profiles:
                return {"error": f"No data for component '{component}'"}
            p = self._profiles[component]
            return {
                "component": component,
                "total_calls": p.total_calls,
                "success_rate": round(p.success_rate, 4),
                "avg_duration_ms": round(p.avg_duration_ms, 2),
                "p95_duration_ms": round(p.p95_duration_ms, 2),
                "failures": p.failures,
            }

    def get_all_profiles(self) -> Dict[str, Dict[str, Any]]:
        """Get performance profiles for all tracked components."""
        with self._lock:
            return {name: self.get_profile(name) for name in self._profiles}

    def get_health_report(self) -> Dict[str, Any]:
        """Generate a full health report with recommendations."""
        with self._lock:
            degraded = []
            slow = []
            healthy = []

            for name, profile in self._profiles.items():
                if profile.total_calls < 3:
                    continue
                if profile.success_rate < self.DEGRADATION_THRESHOLD:
                    degraded.append(name)
                elif (
                    profile.p95_duration_ms
                    > profile.avg_duration_ms * self.SLOWDOWN_FACTOR
                ):
                    slow.append(name)
                else:
                    healthy.append(name)

            recommendations = []
            for comp in degraded:
                p = self._profiles[comp]
                recommendations.append(
                    f"⚠️ {comp}: success rate {p.success_rate:.0%} — "
                    f"review error logs and input validation"
                )
            for comp in slow:
                p = self._profiles[comp]
                recommendations.append(
                    f"🐢 {comp}: p95 latency {p.p95_duration_ms:.0f}ms vs avg {p.avg_duration_ms:.0f}ms — "
                    f"consider caching or async execution"
                )

            return {
                "total_components": len(self._profiles),
                "total_executions": sum(p.total_calls for p in self._profiles.values()),
                "overall_success_rate": round(
                    sum(p.successes for p in self._profiles.values())
                    / max(sum(p.total_calls for p in self._profiles.values()), 1),
                    4,
                ),
                "healthy_components": healthy,
                "degraded_components": degraded,
                "slow_components": slow,
                "recommendations": recommendations,
            }

    # ── Auto-Tuning ────────────────────────────────────────────

    def get_tuning(self, key: str, default: Any = None) -> Any:
        """Get an auto-tuned parameter value."""
        return self._tuning.get(key, default)

    def set_tuning(self, key: str, value: Any) -> None:
        """Set a tuning parameter and persist."""
        with self._lock:
            self._tuning[key] = value
            self._persist_tuning()

    def auto_tune(self) -> Dict[str, Any]:
        """Run auto-tuning based on collected metrics. Returns applied changes."""
        changes = {}
        with self._lock:
            for name, profile in self._profiles.items():
                if profile.total_calls < 10:
                    continue

                # Auto-increase timeout for consistently slow tools
                timeout_key = f"{name}.timeout_seconds"
                if profile.p95_duration_ms > 10000:
                    new_timeout = min(profile.p95_duration_ms * 1.5 / 1000, 300)
                    old = self._tuning.get(timeout_key, "default")
                    self._tuning[timeout_key] = round(new_timeout, 1)
                    changes[timeout_key] = {"old": old, "new": round(new_timeout, 1)}

                # Auto-enable retry for flaky tools
                retry_key = f"{name}.max_retries"
                if profile.success_rate < 0.85 and profile.total_calls > 20:
                    current = self._tuning.get(retry_key, 1)
                    new_retries = min(current + 1, 5)
                    if new_retries != current:
                        self._tuning[retry_key] = new_retries
                        changes[retry_key] = {"old": current, "new": new_retries}

                # Auto-recommend a lighter model tier when inference is too slow
                # We encode this as router.<tier>.preferred_model tuning hints.
                # This fires when the model avg latency exceeds 30 seconds,
                # suggesting the configured model is too heavy for the hardware.
                if name.startswith("router_tier:"):
                    tier = name.split(":", 1)[1]
                    if profile.avg_duration_ms > 30_000 and profile.total_calls >= 5:
                        # Map tier to the next-lighter tier model key
                        lighter = {"large": "medium", "medium": "small"}.get(tier)
                        if lighter:
                            hint_key = f"router.{tier}.preferred_model"
                            hint_val = f"<downgrade-to-{lighter}>"
                            if self._tuning.get(hint_key) != hint_val:
                                self._tuning[hint_key] = hint_val
                                changes[hint_key] = {"old": "default", "new": hint_val}

            if changes:
                self._persist_tuning()

        return changes

    def start_background_tuning(self, interval_seconds: float = 300.0) -> None:
        """Start a recurring background timer that calls auto_tune() every interval.

        Safe to call multiple times — subsequent calls are no-ops if already running.
        """
        with self._lock:
            if getattr(self, "_tuning_timer_active", False):
                return
            self._tuning_timer_active = True

        def _run() -> None:
            try:
                changes = self.auto_tune()
                if changes:
                    logger.info("SelfOptimizer auto-tune applied %d changes: %s", len(changes), changes)
            except Exception as exc:
                logger.warning("SelfOptimizer auto-tune error: %s", exc)
            finally:
                # Reschedule as long as the flag is set
                if getattr(self, "_tuning_timer_active", False):
                    t = threading.Timer(interval_seconds, _run)
                    t.daemon = True
                    t.start()
                    with self._lock:
                        self._active_timer = t

        t = threading.Timer(interval_seconds, _run)
        t.daemon = True
        t.start()
        with self._lock:
            self._active_timer = t
        logger.info("SelfOptimizer background tuning started (interval=%.0fs)", interval_seconds)

    def stop_background_tuning(self) -> None:
        """Stop the background auto-tuning timer."""
        with self._lock:
            self._tuning_timer_active = False
            timer = getattr(self, "_active_timer", None)
        if timer is not None:
            timer.cancel()

    def get_recommended_model_for_tier(self, tier: str) -> Optional[str]:
        """Return optimizer-recommended model for a routing tier, or None.

        The recommendation is written by auto_tune() when a configured model
        is found to be consistently too slow or unreliable for its tier.
        """
        return self._tuning.get(f"router.{tier}.preferred_model")

    def apply_router_correction(self, config: Any) -> None:
        """Mutate a RouterConfig's tiers dict based on accumulated tuning data.

        Called once when the router initialises to apply any persisted corrections.
        """
        with self._lock:
            for tier in ("small", "medium", "large"):
                recommended = self._tuning.get(f"router.{tier}.preferred_model")
                if recommended and hasattr(config, "tiers") and isinstance(config.tiers, dict):
                    current = config.tiers.get(tier)
                    if current != recommended:
                        config.tiers[tier] = recommended
                        logger.info(
                            "SelfOptimizer corrected router tier '%s': %s -> %s",
                            tier, current, recommended,
                        )

    # ── Feedback Loop ──────────────────────────────────────────

    def on_execution(self, callback: Callable[[ExecutionRecord], None]) -> None:
        """Register a callback for every execution event."""
        self._callbacks.append(callback)

    def record_user_feedback(
        self, component: str, rating: int, comment: str = ""
    ) -> None:
        """Record explicit user quality feedback (1-5 scale)."""
        self.record(
            component=component,
            action="user_feedback",
            duration_ms=0,
            success=rating >= 3,
            metadata={"rating": rating, "comment": comment},
        )

    # ── Persistence ────────────────────────────────────────────

    def _load_persisted(self) -> None:
        metrics_file = self._persist_dir / _METRICS_FILE
        tuning_file = self._persist_dir / _TUNING_FILE

        if metrics_file.exists():
            try:
                data = json.loads(metrics_file.read_text(encoding="utf-8"))
                for name, raw in data.items():
                    p = ComponentProfile()
                    p.total_calls = raw.get("total_calls", 0)
                    p.successes = raw.get("successes", 0)
                    p.failures = raw.get("failures", 0)
                    p.total_duration_ms = raw.get("total_duration_ms", 0.0)
                    p.avg_duration_ms = raw.get("avg_duration_ms", 0.0)
                    p.p95_duration_ms = raw.get("p95_duration_ms", 0.0)
                    p.success_rate = raw.get("success_rate", 1.0)
                    self._profiles[name] = p
            except (json.JSONDecodeError, KeyError):
                logger.warning("Corrupt optimizer metrics file, starting fresh")

        if tuning_file.exists():
            try:
                self._tuning = json.loads(tuning_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._tuning = {}

    def persist(self) -> None:
        """Save current metrics and tuning to disk."""
        with self._lock:
            self._persist_metrics()
            self._persist_tuning()

    def _persist_metrics(self) -> None:
        data = {}
        for name, p in self._profiles.items():
            data[name] = {
                "total_calls": p.total_calls,
                "successes": p.successes,
                "failures": p.failures,
                "total_duration_ms": p.total_duration_ms,
                "avg_duration_ms": round(p.avg_duration_ms, 2),
                "p95_duration_ms": round(p.p95_duration_ms, 2),
                "success_rate": round(p.success_rate, 4),
            }
        path = self._persist_dir / _METRICS_FILE
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _persist_tuning(self) -> None:
        path = self._persist_dir / _TUNING_FILE
        path.write_text(json.dumps(self._tuning, indent=2), encoding="utf-8")


# ── Singleton accessor ─────────────────────────────────────────

_global_optimizer: Optional[SelfOptimizer] = None
_init_lock = threading.Lock()


def get_optimizer() -> SelfOptimizer:
    """Get or create the global SelfOptimizer instance."""
    global _global_optimizer
    if _global_optimizer is None:
        with _init_lock:
            if _global_optimizer is None:
                _global_optimizer = SelfOptimizer()
    return _global_optimizer


def track_execution(component: str, action: str = "execute"):
    """Decorator that auto-tracks execution time and success for any function."""

    def decorator(func: Callable) -> Callable:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            optimizer = get_optimizer()
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration = (time.perf_counter() - start) * 1000
                success = True
                if hasattr(result, "success"):
                    success = result.success
                optimizer.record(component, action, duration, success)
                return result
            except Exception as exc:
                duration = (time.perf_counter() - start) * 1000
                optimizer.record(component, action, duration, False, error=str(exc))
                raise

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator


__all__ = [
    "SelfOptimizer",
    "ExecutionRecord",
    "ComponentProfile",
    "get_optimizer",
    "track_execution",
]
