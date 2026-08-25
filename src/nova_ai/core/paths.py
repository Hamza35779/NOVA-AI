"""Central, env-aware resolution of NOVA AI' home directory.

NOVA AI keeps all of its runtime state (config, databases, caches, logs,
credentials, skills, recipes, …) under a single root so it never clutters the
user's home directory beyond one directory. That root is resolved here, with
the following precedence (highest first):

1. ``$NOVA_AI_HOME`` — explicit override (also honored by the shell
   installer, see ``scripts/install/install.sh``).
2. ``$XDG_DATA_HOME/nova_ai`` — when ``$XDG_DATA_HOME`` is set, follow the
   XDG Base Directory spec by nesting a single ``nova_ai`` directory under
   it. We deliberately use ONE directory rather than splitting across XDG
   config/data/cache so the install tree stays self-contained and relocatable.
3. ``~/.nova_ai`` — the historical default. With no env vars set, the
   resolved path is exactly this, so existing installs are untouched.

``config.py`` re-exports :func:`get_config_dir` results through the legacy
``DEFAULT_CONFIG_DIR``/``DEFAULT_CONFIG_PATH`` names (computed dynamically) so
the ~45 modules that import those names keep working while honoring the
override. Modules that previously hardcoded ``Path.home() / ".nova_ai"``
should call :func:`get_config_dir` (or :func:`get_data_dir` /
:func:`get_cache_dir`) instead.

Defense in depth: the resolved root must never live inside the NOVA AI
source tree (a misconfigured ``$NOVA_AI_HOME`` pointing at the repo would
otherwise scatter runtime artifacts into the working tree). The detector is
shared with ``learning/spec_search/storage/paths.py`` (which imports it from
here) and fails loudly per REVIEW.md's no-silent-failure discipline.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_DEFAULT_DIR_NAME = ".nova_ai"
_XDG_SUBDIR_NAME = "nova_ai"

# Matches the ``[project] name`` line of this project's pyproject.toml in
# any spelling (``"novaai"`` as published / ``"nova-ai"`` historically /
# ``"nova_ai"`` as imported). Anchored to a whole TOML key-value line so a
# stray mention elsewhere in the file can never false-positive.
_PROJECT_NAME_LINE = re.compile(
    r"^name\s*=\s*[\"']nova[-_]?ai[\"']\s*$", re.MULTILINE | re.IGNORECASE
)


class ConfigurationError(RuntimeError):
    """Raised when the resolved home directory would violate isolation guarantees."""


def _find_source_root() -> Path | None:
    """Walk upward from this module to find the NOVA AI source root.

    Returns the directory containing the NOVA AI ``pyproject.toml`` (the one
    whose ``name = "nova_ai"``), or ``None`` when running from an installed
    wheel rather than a source checkout.
    """
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        py = candidate / "pyproject.toml"
        if py.exists():
            try:
                content = py.read_text(encoding="utf-8")
            except OSError:
                continue
            if _PROJECT_NAME_LINE.search(content):
                return candidate
    return None


def _reject_source_tree(path: Path) -> Path:
    """Raise if ``path`` resolves inside the NOVA AI source tree."""
    source_root = _find_source_root()
    if source_root is not None:
        try:
            path.relative_to(source_root)
        except ValueError:
            pass  # Good — not inside the source tree.
        else:
            raise ConfigurationError(
                f"NOVA AI home ({path}) is inside the source tree "
                f"({source_root}). NOVA AI refuses to write runtime state "
                "inside its own repo. Set NOVA_AI_HOME (or XDG_DATA_HOME) "
                "to a directory outside the repo (default: ~/.nova_ai)."
            )
    return path


def get_config_dir() -> Path:
    """Resolve NOVA AI' single root directory, honoring env overrides.

    Precedence: ``$NOVA_AI_HOME`` > ``$XDG_DATA_HOME/nova_ai`` >
    ``~/.nova_ai``. The result is always absolute and is rejected if it
    falls inside the NOVA AI source tree.
    """
    env_home = os.environ.get("NOVA_AI_HOME")
    if env_home:
        resolved = Path(env_home).expanduser().resolve()
        return _reject_source_tree(resolved)

    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        resolved = (Path(xdg_data).expanduser() / _XDG_SUBDIR_NAME).resolve()
        return _reject_source_tree(resolved)

    return (Path.home() / _DEFAULT_DIR_NAME).resolve()


def get_config_path() -> Path:
    """Resolve the path to ``config.toml`` under the NOVA AI root."""
    return get_config_dir() / "config.toml"


def get_data_dir() -> Path:
    """Resolve the directory for persistent data (databases, blobs, …).

    Consolidated under the single root; identical to :func:`get_config_dir`.
    Provided as a distinct name so call sites read intentionally.
    """
    return get_config_dir()


def get_cache_dir() -> Path:
    """Resolve the directory for regenerable caches (eval datasets, etc.).

    Lives at ``<root>/cache`` so caches stay inside the single NOVA AI
    directory instead of scattering across ``~/.cache``.
    """
    return get_config_dir() / "cache"
