"""Smart Model Router — dynamic complexity-aware inference routing."""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Sequence

from nova_ai.core.types import Message
from nova_ai.engine._stubs import InferenceEngine, StreamChunk
from nova_ai.engine.multi import MultiEngine
from nova_ai.engine.router_config import RouterConfig
from nova_ai.engine.router_learning import get_feedback_store
from nova_ai.engine.self_optimizer import get_optimizer

logger = logging.getLogger(__name__)

# Precompiled regex patterns for zero-overhead classification
_RE_CODE_BLOCK = re.compile(
    r"```|^\s*(?:def\s+|class\s+|fn\s+|function\s+|const\s+|import\s+|from\s+|SELECT\s+)",
    re.MULTILINE | re.IGNORECASE,
)
_RE_RESEARCH_KEYWORDS = re.compile(
    r"\b(analyze|analysis|compare|comparison|research|investigate|evaluate|critique|synthesize|"
    r"explain in detail|step[- ]by[- ]step|pros and cons|architect|tradeoffs?|deep dive|deriv(?:e|ation)|"
    r"implement|refactor|debug|optimize|benchmark)\b",
    re.IGNORECASE,
)
_RE_SMALL_KEYWORDS = re.compile(
    r"\b(?:hello|hi|hey|greetings|what time is it|what is the date|yes|no|ok|okay|thanks|thank you|ping|who are you)\b",
    re.IGNORECASE,
)


class SmartRouter(InferenceEngine):
    """Complexity-aware inference router that balances intelligence and speed."""

    def __init__(
        self, engine: MultiEngine, config: Optional[RouterConfig] = None
    ) -> None:
        self.engine = engine
        self.config = config or RouterConfig()
        self._lock = threading.Lock()
        self._stats: Dict[str, Any] = {
            "small": 0,
            "medium": 0,
            "large": 0,
            "bypassed": 0,
            "total_requests": 0,
            "total_latency_seconds": 0.0,
        }
        # Apply any persisted optimizer corrections to tier config
        optimizer = get_optimizer()
        optimizer.apply_router_correction(self.config)
        # Start background auto-tuning (no-op if already running)
        optimizer.start_background_tuning(interval_seconds=300)

    def classify_complexity(self, messages: Sequence[Message], **kwargs: Any) -> str:
        """Classify message history into 'small', 'medium', or 'large' tier."""
        # Get heuristic tier first
        heuristic_tier = self._classify_heuristic(messages, **kwargs)

        # Apply learned correction if enabled
        if self.config.learning_enabled:
            try:
                last_content = messages[-1].content or "" if messages else ""
                store = get_feedback_store()
                corrected = store.get_correction(last_content, heuristic_tier)
                if corrected:
                    logger.debug(
                        "Router learning: overriding '%s' -> '%s' based on feedback",
                        heuristic_tier, corrected,
                    )
                    return corrected
            except Exception:
                pass  # Never let learning break routing

        return heuristic_tier

    def _classify_heuristic(self, messages: Sequence[Message], **kwargs: Any) -> str:
        if not messages:
            return self.config.default_tier

        # Tool execution always needs at least medium tier capabilities
        # (empty tool lists are common in generic calls — only honor non-empty).
        tools = kwargs.get("tools")
        if tools:
            return self.config.tool_use_tier

        # Check for code blocks or coding tasks -> large/code tier
        last_msg = messages[-1]
        last_content = last_msg.content or ""

        if _RE_CODE_BLOCK.search(last_content):
            return self.config.code_tier

        # System prompt complexity check
        system_prompts = [msg for msg in messages if msg.role == "system"]
        if system_prompts and any(len(p.content or "") > 500 for p in system_prompts):
            return self.config.tool_use_tier

        # Research and deep reasoning keywords
        if _RE_RESEARCH_KEYWORDS.search(last_content):
            return self.config.research_tier

        total_length = sum(len(msg.content or "") for msg in messages)
        num_messages = len(messages)

        # Fast greetings and single-turn trivial queries. Match anywhere so
        # mid-sentence confirmations ("yes please continue") still classify small.
        if (
            _RE_SMALL_KEYWORDS.search(last_content)
            and total_length < self.config.short_query_max_chars
        ):
            return "small"

        # Weighted multi-signal scoring: length pressure (70%) + conversation
        # depth pressure (30%). Hard cutoffs are preserved for the extremes.
        length_pressure = min(
            total_length / max(1, self.config.medium_query_max_chars), 2.0
        )
        depth_pressure = max(0, num_messages - 1) / 4.0
        complexity_score = 0.7 * length_pressure + 0.3 * depth_pressure

        if (
            complexity_score >= 0.85
            or total_length > self.config.medium_query_max_chars
            or num_messages >= 5
        ):
            return "large"
        if total_length < self.config.short_query_max_chars and num_messages <= 2:
            return "small"

        return self.config.default_tier

    def record_feedback(
        self,
        message_id: str,
        query_content: str,
        tier_chosen: str,
        thumbs_up: bool,
    ) -> None:
        """Record user feedback on a routing decision to improve future routing."""
        if not self.config.learning_enabled:
            return
        try:
            store = get_feedback_store()
            store.record_implicit_feedback(message_id, query_content, tier_chosen, thumbs_up)
        except Exception as exc:
            logger.debug("Router feedback store error: %s", exc)

    def _resolve_model(self, tier: str) -> str:
        """Resolve model name for a tier with dynamic engine discovery fallback."""
        # Check if the self-optimizer has a recommendation for this tier
        optimizer = get_optimizer()
        optimizer_rec = optimizer.get_recommended_model_for_tier(tier)
        if optimizer_rec and not optimizer_rec.startswith("<"):
            return optimizer_rec

        configured = self.config.tiers.get(
            tier, self.config.tiers.get(self.config.default_tier, "qwen2.5:7b")
        )
        # Verify if engine can serve the configured model
        if hasattr(self.engine, "can_serve") and self.engine.can_serve(configured):
            return configured

        # If model is directly listed in engine's models, use it
        try:
            available = self.engine.list_models()
            if configured in available:
                return configured
            if available:
                # Pick best available based on tier
                if tier == "small":
                    return available[0]
                elif tier == "large":
                    return available[-1]
                return available[len(available) // 2]
        except Exception:
            pass

        return configured

    def generate(self, messages: Sequence[Message], **kwargs: Any) -> Dict[str, Any]:
        start_time = time.perf_counter()

        model = kwargs.pop("model", None)
        if model is not None:
            result = self.engine.generate(messages, model=model, **kwargs)
            with self._lock:
                self._stats["total_requests"] += 1
                self._stats["bypassed"] += 1
                self._stats["total_latency_seconds"] += time.perf_counter() - start_time
            return result

        tier = self.classify_complexity(messages, **kwargs)
        routed_model = self._resolve_model(tier)
        logger.info(
            "SmartRouter routed query to '%s' tier (model=%s)", tier, routed_model
        )

        # Record the routing decision with timing so the optimizer can learn
        _route_start = time.perf_counter()

        result = self.engine.generate(messages, model=routed_model, **kwargs)

        get_optimizer().record(
            component=f"router_tier:{tier}",
            action="generate",
            duration_ms=(time.perf_counter() - _route_start) * 1000,
            success=True,
        )

        with self._lock:
            self._stats["total_requests"] += 1
            self._stats[tier] = self._stats.get(tier, 0) + 1
            self._stats["total_latency_seconds"] += time.perf_counter() - start_time

        # Record the routing decision so feedback can be correlated later
        if self.config.learning_enabled:
            try:
                last_content = messages[-1].content or "" if messages else ""
                msg_id = kwargs.get("message_id", f"msg_{int(time.time() * 1000)}")
                get_feedback_store().record_decision(msg_id, last_content, tier)
            except Exception:
                pass
        return result

    async def stream(
        self, messages: Sequence[Message], **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        model = kwargs.pop("model", None)
        if model is not None:
            with self._lock:
                self._stats["total_requests"] += 1
                self._stats["bypassed"] += 1
            async for chunk in self.engine.stream(messages, model=model, **kwargs):
                yield chunk
            return

        tier = self.classify_complexity(messages, **kwargs)
        routed_model = self._resolve_model(tier)
        logger.info(
            "SmartRouter routed stream to '%s' tier (model=%s)", tier, routed_model
        )
        with self._lock:
            self._stats["total_requests"] += 1
            self._stats[tier] = self._stats.get(tier, 0) + 1

        async for chunk in self.engine.stream(messages, model=routed_model, **kwargs):
            yield chunk

    async def stream_full(
        self, messages: Sequence[Message], **kwargs: Any
    ) -> AsyncGenerator[StreamChunk, None]:
        model = kwargs.pop("model", None)
        if model is not None:
            with self._lock:
                self._stats["total_requests"] += 1
                self._stats["bypassed"] += 1
            async for chunk in self.engine.stream_full(messages, model=model, **kwargs):
                yield chunk
            return

        tier = self.classify_complexity(messages, **kwargs)
        routed_model = self._resolve_model(tier)
        logger.info(
            "SmartRouter routed stream_full to '%s' tier (model=%s)", tier, routed_model
        )
        with self._lock:
            self._stats["total_requests"] += 1
            self._stats[tier] = self._stats.get(tier, 0) + 1

        async for chunk in self.engine.stream_full(
            messages, model=routed_model, **kwargs
        ):
            yield chunk

    def list_models(self) -> List[str]:
        return self.engine.list_models()

    def health(self) -> bool:
        return self.engine.health()

    def close(self) -> None:
        self.engine.close()

    def get_routing_stats(self) -> Dict[str, Any]:
        with self._lock:
            stats = self._stats.copy()
        total = stats.get("total_requests", 0)
        total_lat = stats.get("total_latency_seconds", 0.0)
        stats["avg_latency_ms"] = (
            round((total_lat / total) * 1000, 2) if total > 0 else 0.0
        )
        # Don't expose raw accumulator — replace with formatted value
        stats.pop("total_latency_seconds", None)
        return stats


__all__ = ["SmartRouter"]
