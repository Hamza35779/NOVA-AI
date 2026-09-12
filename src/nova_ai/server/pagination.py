"""Cursor pagination + request-ID helpers for API v2.

Fixture from PROJECT_IMPROVEMENTS_EXTENDED.md §10.
New list routes should use :func:`paginate` and echo ``X-Request-ID``;
``/v1`` OpenAI-compat routes stay frozen.
"""

from __future__ import annotations

import uuid
from typing import Any


def paginate(items: list, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
    """Slice ``items`` by opaque cursor (integer offset encoded as str)."""
    try:
        start = int(cursor or 0)
    except (ValueError, TypeError):
        start = 0
    if start < 0:
        start = 0
    limit = max(1, min(limit, 200))
    page = items[start : start + limit]
    next_cursor = str(start + limit) if start + limit < len(items) else None
    return {"items": page, "next_cursor": next_cursor}


def ensure_request_id(headers: dict | None = None) -> str:
    """Return incoming ``X-Request-ID`` or generate a new one."""
    if headers:
        for key in ("X-Request-ID", "x-request-id", "X-Request-Id"):
            if headers.get(key):
                return str(headers[key])
    return uuid.uuid4().hex[:12]
