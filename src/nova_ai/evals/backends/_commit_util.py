"""Shared helper for resolving the nova_ai repo's HEAD commit."""

from __future__ import annotations

import functools
import subprocess
from pathlib import Path


@functools.lru_cache(maxsize=1)
def nova_ai_commit() -> str:
    """Return the nova_ai repo's HEAD commit (cached, lru-1).

    Returns ``"unknown"`` if git is unavailable or the path isn't a repo.
    Used by NovaAgentBackend and NovaDirectBackend to populate the
    ``framework_commit`` field in their extended return dicts.
    """
    try:
        # Walk up to repo root: backends/ -> evals/ -> nova_ai/ -> src/ -> repo
        result = subprocess.run(
            [
                "git",
                "-C",
                str(Path(__file__).resolve().parents[4]),
                "rev-parse",
                "HEAD",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"
