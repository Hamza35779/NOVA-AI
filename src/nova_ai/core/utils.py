"""Small cross-platform utilities used by the CLI, OAuth flow, and evals.

Kept dependency-free so importing this module is cheap (the public re-export
from ``nova_ai.core`` must not pull in heavy modules at package init).
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import webbrowser

logger = logging.getLogger(__name__)


def get_python_executable() -> str:
    """Return the best ``python`` interpreter name on PATH.

    Prefers ``python3`` (Linux/macOS convention); falls back to ``python``
    (Windows / some minimal Linux distros that ship only ``python``). Returns
    the literal string ``"python3"`` when neither is found, so callers still
    get a usable command that will fail with a clear "command not found"
    rather than an empty string.

    The result is a *command name or absolute path* that callers can hand to
    :mod:`subprocess` directly when ``shell=False``, and must be shell-quoted
    (:func:`shlex.quote`) before being interpolated into a ``shell=True``
    command string — paths on Windows often contain spaces.
    """
    return shutil.which("python3") or shutil.which("python") or "python3"


def open_browser(url: str) -> None:
    """Open *url* in the user's default browser, with a Windows fast-path.

    :func:`webbrowser.open` is the cross-platform default, but on Windows it
    sometimes blocks or fails inside a console host. ``cmd /c start "" "URL"``
    is the canonical Windows incantation that hands the URL to the OS shell
    and returns immediately. We try that first on Windows and fall back to
    :func:`webbrowser.open` if the subprocess spawn fails.
    """
    if platform.system() == "Windows":
        try:
            # The empty title argument after ``start`` is required: ``start``
            # treats a single quoted argument as a window title, not a URL.
            subprocess.run(["cmd", "/c", "start", "", url], check=False)
            return
        except Exception as exc:  # noqa: BLE001 - any spawn failure -> fall back
            soft_fail(logger, exc, "cmd.exe start fallback failed")
    webbrowser.open(url)


def soft_fail(
    logger: logging.Logger,
    exc: BaseException,
    context: str,
    level: str = "debug",
) -> None:
    """Log a deliberately-swallowed exception with consistent context.

    The codebase contains hundreds of best-effort ``except Exception`` blocks
    (optional features, telemetry, hardware probing...) where a failure must
    never propagate. Swallowing *silently* makes those paths undebuggable —
    this helper replaces the bare ``pass`` so every swallow leaves one
    consistent, greppable breadcrumb at (by default) DEBUG level.

    Usage::

        try:
            maybe_breaks()
        except Exception as exc:
            soft_fail(logger, exc, "loading optional widget")

    Args:
        logger: Logger to emit through. Use the caller's module logger.
        exc: The caught exception (formatted with type + message).
        context: Short phrase describing what was being attempted;
            rendered as ``"<context>: <ExcType>: <message>"``.
        level: Log level name — ``"debug"`` (default), ``"info"``,
            ``"warning"``, or ``"error"``. Use ``"warning"`` when a swallow
            could plausibly hide a real bug; keep ``"debug"`` for routine
            best-effort paths.
    """
    # A typo'd level would raise AttributeError from inside the very helper
    # that exists to never propagate an exception — validate and fall back.
    if level not in ("debug", "info", "warning", "error", "critical"):
        logger.debug(
            "soft_fail called with unknown level %r; falling back to debug",
            level,
        )
        level = "debug"
    getattr(logger, level)(
        "%s: %s: %s",
        context,
        type(exc).__name__,
        exc,
    )


__all__ = ["get_python_executable", "open_browser", "soft_fail"]
