"""NOVA AI — modular AI assistant backend with composable intelligence primitives.

The public surface (``Nova``, ``NovaSystem``, ``MemoryHandle``, ``SystemBuilder``)
is exposed via :pep:`562` module-level ``__getattr__`` so that importing
``nova_ai`` — which Python does implicitly for ``python -m nova_ai.cli`` — does
not pay the ~1.4s SDK import cost (engine → httpx → tools) on every CLI
invocation. The SDK loads on first attribute access instead.
"""

from __future__ import annotations

import os

_LAZY_EXPORTS = {
    "MemoryHandle": ("nova_ai.sdk", "MemoryHandle"),
    "Nova": ("nova_ai.sdk", "Nova"),
    "NovaSystem": ("nova_ai.sdk", "NovaSystem"),
    "SystemBuilder": ("nova_ai.sdk", "SystemBuilder"),
    # importlib.metadata costs ~260ms at import; defer until read.
    "__version__": (None, None),
}

__all__ = ["Nova", "NovaSystem", "MemoryHandle", "SystemBuilder", "__version__"]

# DEFENSIVE (set before any submodule import): importing ``litellm`` triggers a
# blocking HTTPS fetch of its remote model-cost map
# (litellm/__init__.py -> get_model_cost_map). On machines without direct
# GitHub connectivity the SSL handshake stalls for minutes and freezes
# whichever command imported it (reproduced: `nova doctor` hung >120s with
# zero output; the handshake timeout is ~15s and litellm retries). The local
# backup map bundled with the litellm package is equivalent for NOVA's
# cost/latency reporting. ``setdefault`` keeps a user's own choice authoritative.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")


def _compute_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError
        from importlib.metadata import version as _pkg_version

        # PyPI distribution name is "nova-ai-pro" (see pyproject.toml) — the
        # import package "nova_ai" is not a valid distribution name, so the
        # lookup must target the distribution, not the import package.
        return _pkg_version("nova-ai-pro")
    except PackageNotFoundError:  # pragma: no cover — uninstalled source tree
        return "0.0.0+unknown"


def __getattr__(name: str):
    """PEP 562 lazy export: import the SDK only when actually used."""
    entry = _LAZY_EXPORTS.get(name)
    if entry is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if name == "__version__":
        value = _compute_version()
    else:
        from importlib import import_module

        value = getattr(import_module(entry[0]), entry[1])
    # Cache on the module so repeat lookups skip the machinery.
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_LAZY_EXPORTS})
