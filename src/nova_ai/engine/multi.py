"""Multi-engine wrapper — routes requests to the right backend by model name."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any, Dict, List

from nova_ai.core.types import Message
from nova_ai.engine._base import InferenceEngine
from nova_ai.engine._stubs import StreamChunk

logger = logging.getLogger(__name__)

# Special model alias: let the complexity analyzer choose local vs cloud.
# Roadmap WS3 "query complexity analyzer" — trivial/simple/moderate queries
# stay on the (private, free) local engine; complex ones escalate to cloud.
AUTO_MODEL = "auto"

# Cloud models tried in order when escalating a complex query. Quality-first
# for hard work, with cheaper fallbacks; only the first one actually offered
# by the cloud engine is used.
DEFAULT_CLOUD_MODEL_PREFERENCE = [
    "claude-sonnet-5",
    "gpt-5",
    "gpt-5-mini",
    "gemini-3-flash",
    "deepseek-v4-pro",
]


class MultiEngine(InferenceEngine):
    """Wraps multiple engines and routes by model name.

    Models from each engine are discovered via ``list_models()``.
    When ``generate()`` or ``stream()`` is called, the model name
    is looked up to find which engine owns it.

    ``model="auto"`` (see :data:`AUTO_MODEL`) routes by query complexity:
    the last user message is scored, and queries at or above
    *auto_route_threshold* go to the first preferred cloud model actually
    available; everything else stays on the first local engine. The decision
    is attached to non-streaming results under ``result["_routing"]``.
    """

    engine_id = "multi"

    def __init__(
        self,
        engines: list[tuple[str, InferenceEngine]],
        *,
        auto_route_threshold: float = 0.55,
        cloud_model_preference: List[str] | None = None,
    ) -> None:
        self._engines = engines
        self._auto_route_threshold = auto_route_threshold
        self._cloud_model_preference = (
            cloud_model_preference or DEFAULT_CLOUD_MODEL_PREFERENCE
        )
        self._model_map: Dict[str, InferenceEngine] = {}
        self._refresh_map()

    def _refresh_map(self) -> None:
        self._model_map.clear()
        for _key, engine in self._engines:
            try:
                for model_id in engine.list_models():
                    self._model_map[model_id] = engine
            except Exception as exc:
                logger.debug("Failed to list models for %s: %s", _key, exc)

    _CLOUD_PREFIXES = (
        "gpt-",
        "chatgpt-",
        "o1",
        "o3",
        "o4",
        "claude-",
        "claude",
        "gemini-",
        "gemini",
        "grok-",
        "grok",
        "deepseek-",
        "MiniMax-",
        "minimax",
        "openrouter/",
        "codex/",
    )

    def _engine_for(self, model: str) -> InferenceEngine:
        """Find the engine that owns a model, refreshing the map once if needed."""
        engine = self._model_map.get(model)
        if engine is not None:
            return engine
        # Refresh and retry (a new model may have been pulled)
        self._refresh_map()
        engine = self._model_map.get(model)
        if engine is not None:
            return engine
        # If model looks like a cloud model, route to the cloud engine
        # rather than falling back to the local engine (which would 404).
        if any(model.startswith(p) for p in self._CLOUD_PREFIXES):
            for key, eng in self._engines:
                if key == "cloud":
                    logger.info("Routing cloud model %r to cloud engine", model)
                    return eng
        # Non-cloud models: do NOT silently fall back to cloud. A transient
        # vLLM outage during a long agentic run would otherwise route every
        # call to cloud, producing confusing "invalid model ID" errors
        # across all tasks.
        raise ValueError(
            f"Model {model!r} not found in any engine "
            f"(known: {', '.join(sorted(self._model_map.keys())) or '<none>'}). "
            f"Check that the expected backend (e.g. vLLM server) is reachable."
        )

    # -- complexity-driven auto routing (model="auto") ------------------------

    def _auto_local_model(self) -> str:
        """First model offered by the first non-cloud engine."""
        for _key, engine in self._engines:
            if getattr(engine, "is_cloud", False):
                continue
            try:
                models = engine.list_models()
            except Exception:
                continue
            if models:
                return models[0]
        return ""

    def _resolve_auto(self, messages: Sequence[Message]) -> tuple[str, Dict[str, Any]]:
        """Pick a concrete model for ``model="auto"`` from query complexity.

        Returns ``(model, decision)`` where *decision* is the observability
        record also attached to non-streaming results as ``result["_routing"]``.
        Falls back to the best local model whenever cloud is unavailable or
        the query is below threshold — auto never fails just because no
        cloud key is configured.
        """
        from nova_ai.learning.routing.complexity import score_complexity

        last_user = ""
        for m in reversed(messages):
            if m.role.value == "user" and m.content:
                last_user = m.content
                break

        decision: Dict[str, Any] = {"requested": AUTO_MODEL}
        if not last_user:
            chosen = self._auto_local_model()
            decision.update(route="local", reason="no_user_text", model=chosen)
            return chosen, decision

        result = score_complexity(last_user)
        decision["complexity_score"] = result.score
        decision["complexity_tier"] = result.tier

        if result.score < self._auto_route_threshold:
            chosen = self._auto_local_model()
            decision.update(route="local", reason="below_threshold", model=chosen)
            return chosen, decision

        available = set(self.list_models())
        for candidate in self._cloud_model_preference:
            if candidate in available:
                decision.update(
                    route="cloud",
                    reason="at_or_above_threshold",
                    model=candidate,
                )
                return candidate, decision

        # Complex query but no preferred cloud model is configured/available.
        chosen = self._auto_local_model()
        decision.update(route="local", reason="cloud_unavailable", model=chosen)
        return chosen, decision

    def _maybe_resolve_auto(
        self, messages: Sequence[Message], model: str
    ) -> tuple[str, Dict[str, Any] | None]:
        """Pass through real models; resolve only the "auto" alias."""
        if model != AUTO_MODEL:
            return model, None
        return self._resolve_auto(messages)

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        resolved_model, routing = self._maybe_resolve_auto(messages, model)
        result = self._engine_for(resolved_model).generate(
            messages,
            model=resolved_model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        if routing is not None:
            # Observability surface for the auto-routing decision; underscore
            # key mirrors "_telemetry" (never collides with API fields).
            result["_routing"] = routing
            logger.info(
                "Auto route: score=%.2f (%s) -> %s %r",
                routing.get("complexity_score", -1.0),
                routing.get("reason"),
                routing.get("route"),
                resolved_model,
            )
        return result

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        resolved_model, _routing = self._maybe_resolve_auto(messages, model)
        async for token in self._engine_for(resolved_model).stream(
            messages,
            model=resolved_model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            yield token

    async def stream_full(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        **kwargs: Any,
    ) -> AsyncIterator["StreamChunk"]:
        """Delegate stream_full() to the engine that owns the model."""
        resolved_model, _routing = self._maybe_resolve_auto(messages, model)
        engine = self._engine_for(resolved_model)
        async for chunk in engine.stream_full(messages, model=resolved_model, **kwargs):
            yield chunk

    def list_models(self) -> List[str]:
        self._refresh_map()
        models = list(self._model_map.keys())
        if len(self._engines) > 1:
            # Advertise the complexity-driven alias only when there is
            # actually something to choose between.
            models.append(AUTO_MODEL)
        return models

    def health(self) -> bool:
        return any(engine.health() for _key, engine in self._engines)

    def close(self) -> None:
        for _key, engine in self._engines:
            engine.close()


__all__ = ["AUTO_MODEL", "DEFAULT_CLOUD_MODEL_PREFERENCE", "MultiEngine"]
