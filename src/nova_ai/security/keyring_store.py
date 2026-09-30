"""OS keyring storage for NOVA AI secrets (audit item B3).

Secrets such as the server API key historically lived in plaintext under
``~/.nova_ai/config.toml``.  This module stores them in the operating
system's credential vault instead (Windows Credential Manager, macOS
Keychain, or a FreeDesktop Secret Service on Linux) via the optional
``keyring`` package (``uv sync --extra security-keyring``).

Design notes:

- The ``keyring`` import is lazy and optional: every function raises
  :class:`KeyringUnavailable` when the package (or a usable backend) is
  missing, so callers can fall back to legacy plaintext storage rather
  than crash.
- Secrets are namespaced under the ``"nova-ai"`` service with
  ``"<scope>:<key>"`` account names (e.g. ``"server:api_key"``).
- Nothing here writes to the config file; migration helpers that do are
  in the calling layers where the TOML editing policy lives.
"""

from __future__ import annotations

from typing import Any, Optional

SERVICE = "nova-ai"

__all__ = [
    "SERVICE",
    "KeyringUnavailable",
    "delete_secret",
    "keyring_available",
    "read_secret",
    "store_secret",
]


class KeyringUnavailable(RuntimeError):
    """Raised when the keyring package or backend is missing/unusable."""


def _keyring() -> Any:
    """Import and return the ``keyring`` module (lazy, typed as Any)."""
    try:
        import keyring  # noqa: PLC0415 — optional dependency, lazy import
    except ImportError as exc:  # pragma: no cover - exercised via fakes
        raise KeyringUnavailable(
            "The 'keyring' package is not installed. "
            "Install it with: uv sync --extra security-keyring"
        ) from exc
    return keyring


def keyring_available() -> bool:
    """Return True when a real (non-failing) keyring backend is usable."""
    try:
        mod = _keyring()
    except KeyringUnavailable:
        return False
    try:
        # Probe the backend once; some environments report a backend that
        # then fails on every operation (headless Linux without a Secret
        # Service, for example).  get_keyring() itself does not touch the
        # vault, so also attempt a harmless priority query.
        backend = mod.get_keyring()
        getattr(backend, "priority", 0)
        return "fail" not in type(backend).__module__.lower()
    except Exception:
        return False


def _account(scope: str, key: str) -> str:
    return f"{scope}:{key}"


def store_secret(scope: str, key: str, value: str) -> None:
    """Store *value* in the OS keyring under ``<scope>:<key>``.

    Raises :class:`KeyringUnavailable` when no usable backend exists and
    propagates backend errors (access denied, locked vault, ...).
    """
    mod = _keyring()
    mod.set_password(SERVICE, _account(scope, key), value)


def read_secret(scope: str, key: str) -> Optional[str]:
    """Read the secret stored under ``<scope>:<key>``, or ``None``.

    A backend error (locked vault, access denied) is re-raised; only the
    plain absence of a secret yields ``None``.
    """
    mod = _keyring()
    return mod.get_password(SERVICE, _account(scope, key))


def delete_secret(scope: str, key: str) -> bool:
    """Delete the secret stored under ``<scope>:<key>``.

    Returns True when a secret was removed, False when none existed.
    (Existence is probed first so no keyring-version-specific exception
    class is needed; a backend failure on an existing secret propagates.)
    """
    mod = _keyring()
    account = _account(scope, key)
    if mod.get_password(SERVICE, account) is None:
        return False
    mod.delete_password(SERVICE, account)
    return True
