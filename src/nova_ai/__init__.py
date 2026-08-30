"""NOVA AI — modular AI assistant backend with composable intelligence primitives."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from nova_ai.sdk import MemoryHandle, Nova, NovaSystem, SystemBuilder

try:
    # PyPI distribution name is "nova-ai-pro" (see pyproject.toml) — the
    # import package "nova_ai" is not a valid distribution name, so the
    # lookup must target the distribution, not the import package.
    __version__ = _pkg_version("nova-ai-pro")
except PackageNotFoundError:  # pragma: no cover — uninstalled source tree
    __version__ = "0.0.0+unknown"

__all__ = ["Nova", "NovaSystem", "MemoryHandle", "SystemBuilder", "__version__"]
