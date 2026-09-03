"""SQLite-backed storage for forge run records.

Clones ``ProvingRunStore`` (stdlib sqlite3, WAL, persistent connection,
thread lock around execute+commit). Lives at
``~/.nova_ai/learning/skillforge/runs.db``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CREATE_RUNS = """\
CREATE TABLE IF NOT EXISTS skillforge_runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'manual',
    skill_name TEXT NOT NULL DEFAULT '',
    pattern_count INTEGER NOT NULL DEFAULT 0,
    sequence TEXT NOT NULL DEFAULT '[]',
    gauntlet TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    error TEXT
);
"""

_INSERT_RUN = """\
INSERT OR REPLACE INTO skillforge_runs (
    id, status, trigger, skill_name, pattern_count, sequence,
    gauntlet, started_at, ended_at, error
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_UPDATE_RUN = """\
UPDATE skillforge_runs SET
    status = ?, skill_name = ?, pattern_count = ?, sequence = ?,
    gauntlet = ?, ended_at = ?, error = ?
WHERE id = ?
"""

_RUN_COLUMNS = (
    "id, status, trigger, skill_name, pattern_count, sequence, "
    "gauntlet, started_at, ended_at, error"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SkillForgeRunStore:
    """SQLite-backed store for forge run records."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_RUNS)
        self._conn.commit()
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- Write API -----------------------------------------------------------

    def start_run(self, run_id: str, *, trigger: str = "manual") -> None:
        """Record a new run in ``running`` state."""
        with self._lock:
            self._conn.execute(
                _INSERT_RUN,
                (run_id, "running", trigger, "", 0, "[]", "{}", _now_iso(), None, None),
            )
            self._conn.commit()

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        skill_name: str = "",
        pattern_count: int = 0,
        sequence: Optional[list[str]] = None,
        gauntlet: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Transition a run to a terminal state."""
        with self._lock:
            self._conn.execute(
                _UPDATE_RUN,
                (
                    status,
                    skill_name,
                    pattern_count,
                    json.dumps(sequence or []),
                    json.dumps(gauntlet or {}),
                    _now_iso(),
                    error,
                    run_id,
                ),
            )
            self._conn.commit()

    # -- Read API ------------------------------------------------------------

    def _row_to_record(self, row: tuple) -> dict[str, Any]:
        return {
            "id": row[0],
            "status": row[1],
            "trigger": row[2],
            "skill_name": row[3],
            "pattern_count": row[4],
            "sequence": json.loads(row[5]),
            "gauntlet": json.loads(row[6]),
            "started_at": row[7],
            "ended_at": row[8],
            "error": row[9],
        }

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM skillforge_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def latest_run(self) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM skillforge_runs "
            "ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return self._row_to_record(row) if row else None

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM skillforge_runs "
            "ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def list_candidate_runs(
        self, *, status: Optional[str] = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Runs with a skill name, optionally filtered by status."""
        if status is not None:
            rows = self._conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM skillforge_runs "
                "WHERE skill_name != '' AND status = ? "
                "ORDER BY started_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM skillforge_runs "
                "WHERE skill_name != '' ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def is_running(self) -> bool:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM skillforge_runs WHERE status = 'running'"
        ).fetchone()
        return bool(row and row[0])


__all__ = ["SkillForgeRunStore"]
