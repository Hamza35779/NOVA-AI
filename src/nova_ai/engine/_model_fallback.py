"""Shared model-reachability helpers.

Every entry point that turns ``intelligence.default_model`` (or a CLI
``--model`` flag) into an actual inference call must avoid dying on a
model that isn't actually installed on the selected engine — the raw
``Ollama returned 404: model 'x' not found`` failure (audit FP-A).
``nova ask``, ``nova chat``, ``nova serve``, the Python SDK and
``SystemBuilder`` all route through this module so they cannot drift.
"""

from __future__ import annotations


def model_reachable_in_list(engine_models: list[str] | None, model: str) -> bool:
    """Best-effort check that ``model`` is in a single engine's model list.

    When the list is empty/unknown (mocked tests, engine hiccup, cloud
    engine that doesn't enumerate), the model is assumed reachable — this
    must never turn into a hard gate.
    """
    if not engine_models:
        return True
    return model in engine_models


def model_reachable(all_models: dict, engine_name: str, model: str) -> bool:
    """Best-effort check that ``model`` is installed on ``engine_name``.

    Uses the discovery snapshot when it lists models for the engine. When
    discovery returned nothing useful (mocked tests, unknown engine), the
    model is assumed reachable — this must never turn into a hard gate.
    """
    return model_reachable_in_list(all_models.get(engine_name), model)


def pick_fallback_from_engine_models(
    engine_models: list[str] | None,
    configured_model: str,
    fallback_model: str | None = None,
) -> str | None:
    """Return a reachable replacement for an unreachable model, else ``None``.

    Prefers the configured ``intelligence.fallback_model``, then the first
    model the engine actually lists. Returns ``None`` when the configured
    model is reachable or no better candidate exists — callers keep the
    configured model in that case; this must never become a hard gate.
    """
    if model_reachable_in_list(engine_models, configured_model):
        return None
    fallback = fallback_model or next(iter(engine_models or []), None)
    if fallback and fallback != configured_model:
        return fallback
    return None


def pick_reachable_fallback(
    all_models: dict,
    engine_name: str,
    configured_model: str,
    fallback_model: str | None = None,
) -> str | None:
    """Discovery-snapshot variant of :func:`pick_fallback_from_engine_models`."""
    if model_reachable(all_models, engine_name, configured_model):
        return None
    return pick_fallback_from_engine_models(
        all_models.get(engine_name) or [],
        configured_model,
        fallback_model,
    )


def unreachable_model_notice(configured_model: str, fallback: str) -> str:
    """Plain-text notice for a configured-but-unreachable model.

    Callers wrap it in console styling (e.g. ``[yellow]...[/yellow]``).
    """
    return (
        f"Configured model {configured_model!r} is not reachable; "
        f"using {fallback!r}. To install it, run "
        f"'nova model pull {configured_model}' or pick an installed "
        f"model in the Model Hub."
    )


__all__ = [
    "model_reachable",
    "model_reachable_in_list",
    "pick_fallback_from_engine_models",
    "pick_reachable_fallback",
    "unreachable_model_notice",
]
