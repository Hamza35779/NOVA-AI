"""Shared model-reachability helpers for the CLI entry points.

``nova ask``, ``nova chat`` and ``nova serve`` must all avoid dying on a
configured model that isn't actually installed on the selected engine
(audit FP-A: the raw ``Ollama returned 404: model 'x' not found`` error).
This module holds the single best-effort reachability check so the
commands cannot drift apart.
"""

from __future__ import annotations


def model_reachable(all_models: dict, engine_name: str, model: str) -> bool:
    """Best-effort check that ``model`` is installed on ``engine_name``.

    Uses the discovery snapshot when it lists models for the engine. When
    discovery returned nothing useful (mocked tests, unknown engine), the
    model is assumed reachable — this must never turn into a hard gate.
    """
    engine_models = all_models.get(engine_name)
    if not engine_models:
        return True
    return model in engine_models


def pick_reachable_fallback(
    all_models: dict,
    engine_name: str,
    configured_model: str,
    fallback_model: str | None = None,
) -> str | None:
    """Return a reachable replacement for an unreachable model, else ``None``.

    Prefers the configured ``intelligence.fallback_model``, then the first
    model discovered on the engine. Returns ``None`` when the configured
    model is reachable or no better candidate exists — callers keep the
    configured model in that case; this must never become a hard gate.
    """
    if model_reachable(all_models, engine_name, configured_model):
        return None
    fallback = fallback_model or next(iter(all_models.get(engine_name, []) or []), None)
    if fallback and fallback != configured_model:
        return fallback
    return None


__all__ = ["model_reachable", "pick_reachable_fallback"]
