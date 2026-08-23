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

    def classify_complexity(self, messages: Sequence[Message], **kwargs: Any) -> str:
        """Classify message history into 'small', 'medium', or 'large' tier."""
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

    def _resolve_model(self, tier: str) -> str:
        """Resolve model name for a tier with graceful fallback to default."""
        return self.config.tiers.get(
            tier, self.config.tiers.get(self.config.default_tier, "qwen2.5:7b")
        )

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

        result = self.engine.generate(messages, model=routed_model, **kwargs)
        with self._lock:
            self._stats["total_requests"] += 1
            self._stats[tier] = self._stats.get(tier, 0) + 1
            self._stats["total_latency_seconds"] += time.perf_counter() - start_time
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
