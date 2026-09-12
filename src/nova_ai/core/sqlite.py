"""Central SQLite connect helper — WAL + busy_timeout everywhere.

Fixes forensic finding: `busy_timeout` never set while server background sync +
API handlers write concurrently → intermittent `database is locked`.
Use: `from nova_ai.core.sqlite import connect; conn = connect(path)`
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

BUSY_TIMEOUT_MS = 30_000


def connect(db_path: str | Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open SQLite with WAL, 30s busy timeout, foreign-keys on."""
    if str(db_path) == ":memory:":
        conn = sqlite3.connect(":memory:", check_same_thread=False)
    elif read_only:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    else:
        p = Path(db_path)
        if str(p) not in (":memory:",):
            p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
    try:
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS};")
        if not read_only and str(db_path) != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
    except sqlite3.DatabaseError:
        pass
    return conn
