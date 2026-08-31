"""Read background-work state from ``~/.nova_ai/.state/``.

Pure-function reader used by the chat banner, completion-notification
dispatcher, and ``nova doctor``.  No side effects — safe to call
between every chat turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from nova_ai.core import config


@dataclass(slots=True)
class BgStatus:
    """Snapshot of background-work state."""

    rust_extension: str = "pending"  # pending | ready | failed
    rust_error: str = ""
    models: Dict[str, str] = field(
        default_factory=dict
    )  # id -> pending|downloading|ready|failed

    def all_ready(self) -> bool:
        if self.rust_extension != "ready":
            return False
        if any(s != "ready" for s in self.models.values()):
            return False
        return True


def _safe_read(path: Path) -> Optional[str]:
    """Read a file, returning None if it disappears mid-read (race)."""
    try:
        return path.read_text()
    except FileNotFoundError:
        return None


_MODEL_STATE_SUFFIXES = (".downloading", ".ready", ".failed")


def _parse_model_state_file(filename: str) -> Optional[tuple[str, str]]:
    """Parse ``<model-id><state>.downloading|.ready|.failed``.

    Returns ``(model_id, state)`` or None when the name doesn't match.
    Model ids contain dots, so the state suffix is matched at the end of
    the name rather than via ``Path.suffix``. On Windows the install
    scripts sanitize ``:`` to ``_`` in state filenames (NTFS treats a
    colon as an ADS separator); reading restores the single colon.
    """
    for suffix in _MODEL_STATE_SUFFIXES:
        if not filename.endswith(suffix):
            continue
        stem = filename[: -len(suffix)]
        if not stem:
            return None
        if "_" in stem and ":" not in stem:
            # Sanitized Windows filename: restore "<name>:<tag>".
            stem = stem.replace("_", ":", 1)
        return stem, suffix.lstrip(".")
    return None


def get_status(home: Optional[Path] = None) -> BgStatus:
    """Snapshot the background-work state from the state directory."""
    home = home or config.DEFAULT_CONFIG_DIR
    state_dir = home / ".state"
    models_dir = state_dir / "models"

    status = BgStatus()

    # Rust extension: ready supersedes failed; failed supersedes pending.
    if (state_dir / "extension-built").exists():
        status.rust_extension = "ready"
    elif (state_dir / "extension-failed").exists():
        contents = _safe_read(state_dir / "extension-failed")
        if contents is not None:
            status.rust_extension = "failed"
            status.rust_error = contents

    # Models: parse files in models_dir; .ready supersedes .downloading and .failed.
    #
    # Two filename pitfalls, both handled by _parse_model_state_file:
    #   1. Model ids contain dots ("qwen3.5:9b"), so pathlib's f.suffix
    #      is wrong — match the full state suffix at the end of the name.
    #   2. On Windows, ':' is the NTFS alternate-data-stream separator:
    #      writing "qwen3.5:9b.downloading" silently creates "qwen3.5"
    #      plus an ADS. The install scripts therefore sanitize ':' to '_'
    #      on write (see pull-model.sh), and we restore it on read —
    #      Ollama ids are "<name>:<tag>" with exactly one colon and never
    #      contain '_'.
    if models_dir.is_dir():
        # First pass: capture every model id we see.
        seen: Dict[str, str] = {}
        for f in models_dir.iterdir():
            parsed = _parse_model_state_file(f.name)
            if parsed is None:
                continue
            model_id, new_state = parsed
            current = seen.get(model_id, "")
            # Precedence: ready > failed > downloading
            if current == "ready":
                continue
            if new_state == "ready":
                seen[model_id] = "ready"
            elif new_state == "failed" and current != "ready":
                seen[model_id] = "failed"
            elif new_state == "downloading" and current == "":
                seen[model_id] = "downloading"
        status.models = seen

    return status
