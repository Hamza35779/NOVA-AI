"""SQLite-backed persistence for dev-watch run history.

The in-memory ring in ``devwatch_router`` keeps the hot path fast, but a
server restart would wipe it. This store mirrors every recorded run to
``~/.nova_ai/devwatch.db`` so the Dashboard's Build Diagnostics panel
survives restarts. All failures are soft: persistence problems must never
break recording or serving runs.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

_CREATE_RUNS = """\
CREATE TABLE IF NOT EXISTS devwatch_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    command       TEXT    NOT NULL,
    status        TEXT    NOT NULL,
    returncode    INTEGER NOT NULL DEFAULT 0,
    failure_type  TEXT,
    output        TEXT    NOT NULL DEFAULT '',
    suggestion    TEXT    NOT NULL DEFAULT '',
    at            TEXT    NOT NULL
);
"""

_CREATE_INDEX = "CREATE INDEX IF NOT EXISTS idx_devwatch_at ON devwatch_runs(at);"

_INSERT = """\
INSERT INTO devwatch_runs (command, status, returncode, failure_type, output, suggestion, at)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_RECENT = """\
SELECT command, status, returncode, failure_type, output, suggestion, at
FROM devwatch_runs
ORDER BY id DESC
LIMIT ?
"""

_SELECT_COUNT = "SELECT COUNT(*) FROM devwatch_runs"

# Keep the table bounded: the in-memory ring holds 50; persist a multiple
# so the Dashboard can chart a longer history without growing forever.
_MAX_PERSISTED = 500
_PRUNE = """\
DELETE FROM devwatch_runs WHERE id NOT IN (
    SELECT id FROM devwatch_runs ORDER BY id DESC LIMIT ?
)
"""


class DevWatchStore:
    """Append-only SQLite store for dev-watch runs (best-effort persistence)."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            from nova_ai.core.paths import get_config_dir

            db_path = get_config_dir() / "devwatch.db"
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        try:
            if self._db_path != ":memory:":
                from nova_ai.security.file_utils import secure_create

                secure_create(Path(self._db_path))
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(_CREATE_RUNS)
            self._conn.execute(_CREATE_INDEX)
            self._conn.commit()
        except Exception:
            # Persistence is best-effort; the router's in-memory ring still
            # works when the DB cannot be opened (read-only home, corrupt
            # file, ...). Callers treat a None connection as "disabled".
            self._conn = None

    @property
    def available(self) -> bool:
        return self._conn is not None

    def record(self, entry: Dict[str, Any]) -> bool:
        """Persist one run entry; returns True when written."""
        conn = self._conn
        if conn is None:
            return False
        try:
            with self._lock:
                conn.execute(
                    _INSERT,
                    (
                        str(entry.get("command", "")),
                        str(entry.get("status", "")),
                        int(entry.get("returncode", 0) or 0),
                        entry.get("failure_type"),
                        str(entry.get("output", "")),
                        str(entry.get("suggestion", "")),
                        str(entry.get("at", "")),
                    ),
                )
                conn.execute(_PRUNE, (_MAX_PERSISTED,))
                conn.commit()
            return True
        except Exception:
            return False

    def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Most recent runs, newest first. Empty list when unavailable."""
        conn = self._conn
        if conn is None:
            return []
        try:
            with self._lock:
                rows = conn.execute(_SELECT_RECENT, (max(1, limit),)).fetchall()
        except Exception:
            return []
        return [
            {
                "command": r[0],
                "status": r[1],
                "returncode": r[2],
                "failure_type": r[3],
                "output": r[4],
                "suggestion": r[5],
                "at": r[6],
            }
            for r in rows
        ]

    def count(self) -> int:
        conn = self._conn
        if conn is None:
            return 0
        try:
            with self._lock:
                row = conn.execute(_SELECT_COUNT).fetchone()
            return int(row[0]) if row else 0
        except Exception:
            return 0

    def close(self) -> None:
        conn = self._conn
        self._conn = None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
