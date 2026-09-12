"""Shared Google OAuth helpers: 401 refresh + transient-failure retry.

All Google connectors (Gmail, Calendar, Contacts, Drive, Tasks) authenticate
with the same OAuth flow and store identical token payloads at
``~/.nova_ai/connectors/*.json`` — typically a shared ``google.json`` file
plus per-product copies. They all need the same refresh-on-401 behavior, so
the wrapper lives here instead of being duplicated per connector.

Use ``call_with_refresh(api_fn, credentials_path, *args, **kwargs)`` around
any token-taking API helper. On a 401 the wrapper exchanges the stored
``refresh_token`` for a new ``access_token``, updates the credentials file,
and retries the call once. 429 (with ``Retry-After``) and 5xx responses are
retried with bounded backoff; all other status codes propagate.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Optional

import httpx

from nova_ai.connectors.oauth import load_tokens, save_tokens

logger = logging.getLogger(__name__)


_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Transient-failure retry policy (429 / 5xx): 3 retries with exponential
# backoff, honouring Retry-After. Matches _slack_api_with_retry's budget.
_MAX_RETRIES = 3
_MAX_BACKOFF_SECONDS = 30.0


class GoogleAuthError(RuntimeError):
    """Raised when Google credentials are missing or refresh-token grant fails."""


def current_access_token(credentials_path: str) -> str:
    """Return the current access token from the credentials file (empty if absent)."""
    tokens = load_tokens(credentials_path) or {}
    return tokens.get("access_token", tokens.get("token", ""))


def refresh_access_token(credentials_path: str) -> str:
    """Exchange the stored refresh_token for a fresh access_token and persist it.

    Returns the new access_token. Raises :class:`GoogleAuthError` when the
    credentials file is missing, lacks a refresh_token / client credentials,
    or when Google rejects the refresh grant (e.g. the refresh_token has been
    revoked and the user needs to re-authenticate).
    """
    tokens = load_tokens(credentials_path)
    if not tokens:
        raise GoogleAuthError(
            f"No credentials at {credentials_path}; re-run the connector OAuth flow."
        )
    refresh_token = tokens.get("refresh_token", "")
    client_id = tokens.get("client_id", "")
    client_secret = tokens.get("client_secret", "")
    if not (refresh_token and client_id and client_secret):
        raise GoogleAuthError(
            "Stored Google credentials are missing refresh_token / client_id / "
            "client_secret; re-run the connector OAuth flow to mint a full token."
        )

    resp = httpx.post(
        _GOOGLE_TOKEN_ENDPOINT,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30.0,
    )
    if resp.status_code != 200:
        raise GoogleAuthError(
            f"Google token refresh failed ({resp.status_code}): {resp.text[:200]}"
        )
    payload = resp.json()
    new_token = payload.get("access_token", "")
    if not new_token:
        raise GoogleAuthError(
            "Google token refresh returned 200 but no access_token in payload."
        )

    tokens["access_token"] = new_token
    # Keep the legacy "token" key in sync for older code paths that read it.
    tokens["token"] = new_token
    if "expires_in" in payload:
        tokens["expires_in"] = payload["expires_in"]
    save_tokens(credentials_path, tokens)
    logger.info(
        "Refreshed Google access token (expires_in=%s)", payload.get("expires_in")
    )
    return new_token


def call_with_refresh(
    api_fn: Callable[..., Dict[str, Any]],
    credentials_path: str,
    *args: Any,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Invoke ``api_fn(token, *args, **kwargs)`` with 401 refresh + 429/5xx retry.

    Loads the current access token from disk, calls the helper, and if Google
    returns 401 (the access token has expired or been revoked) uses the stored
    refresh_token to mint a new access_token, updates the credentials file,
    and retries the call exactly once.

    Transient failures — 429 with a ``Retry-After`` header and 5xx server
    errors — are retried with bounded backoff (mirrors Slack's
    ``_slack_api_with_retry``) so a single rate-limited page no longer aborts
    an entire sync mid-run. 4xx errors other than 401/429 are permanent and
    re-raised immediately.
    """
    token = current_access_token(credentials_path)
    attempts = 0
    while True:
        try:
            return api_fn(token, *args, **kwargs)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0

            if status == 401:
                logger.info(
                    "Google returned 401 on %s — refreshing access token and"
                    " retrying.",
                    getattr(api_fn, "__name__", "<api_fn>"),
                )
                token = refresh_access_token(credentials_path)
                continue

            if status == 429 or status >= 500:
                attempts += 1
                if attempts > _MAX_RETRIES:
                    raise
                delay = _retry_delay(exc.response, attempts)
                logger.warning(
                    "Google returned %s on %s (attempt %d/%d) — retrying in %.1fs.",
                    status,
                    getattr(api_fn, "__name__", "<api_fn>"),
                    attempts,
                    _MAX_RETRIES,
                    delay,
                )
                time.sleep(delay)
                continue

            raise


def _retry_delay(response: Optional[httpx.Response], attempt: int) -> float:
    """Backoff delay for a retryable Google response.

    Honours ``Retry-After`` when present (seconds), otherwise exponential
    backoff starting at 1s, capped at 30s.
    """
    if response is not None:
        retry_after = getattr(response, "headers", None)
        if retry_after is not None:
            value = retry_after.get("Retry-After")
            if value:
                try:
                    return min(float(value), _MAX_BACKOFF_SECONDS)
                except (TypeError, ValueError):
                    pass
    return min(2 ** (attempt - 1), _MAX_BACKOFF_SECONDS)


__all__ = [
    "GoogleAuthError",
    "current_access_token",
    "refresh_access_token",
    "call_with_refresh",
    "_retry_delay",
]
