"""SQLite-backed storage for proving run records.

Mirrors ``TrainingRunStore`` (stdlib ``sqlite3`` in WAL mode, inline DDL,
persistent connection). Lives at ``~/.nova_ai/learning/proving/runs.db`` —
separate file from the training runs db.

``nova prove status`` / ``nova prove list`` read from here.
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
CREATE TABLE IF NOT EXISTS proving_runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'manual',
    candidate TEXT NOT NULL DEFAULT '',
    incumbent TEXT NOT NULL DEFAULT '',
    samples INTEGER NOT NULL DEFAULT 0,
    per_class TEXT NOT NULL DEFAULT '{}',
    adopted TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    error TEXT
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_prove_runs_started_at ON proving_runs(started_at)",
    "CREATE INDEX IF NOT EXISTS idx_prove_runs_status ON proving_runs(status)",
]

_INSERT_RUN = """\
INSERT OR REPLACE INTO proving_runs (
    id, status, trigger, candidate, incumbent, samples,
    per_class, adopted, started_at, ended_at, error
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_UPDATE_RUN = """\
UPDATE proving_runs SET
    status = ?, samples = ?, per_class = ?, adopted = ?,
    ended_at = ?, error = ?
WHERE id = ?
"""

_RUN_COLUMNS = (
    "id, status, trigger, candidate, incumbent, samples, per_class, "
    "adopted, started_at, ended_at, error"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProvingRunStore:
    """SQLite-backed store for proving run records."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_RUNS)
        for idx in _CREATE_INDEXES:
            self._conn.execute(idx)
        self._conn.commit()
        # One shared connection across threads: serialize execute+commit
        # pairs so interleaved autocommit bookkeeping can't corrupt state.
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- Write API -----------------------------------------------------------

    def start_run(
        self,
        run_id: str,
        *,
        trigger: str = "manual",
        candidate: str = "",
        incumbent: str = "",
    ) -> None:
        """Record a new run in ``running`` state."""
        with self._lock:
            self._conn.execute(
                _INSERT_RUN,
                (
                    run_id,
                    "running",
                    trigger,
                    candidate,
                    incumbent,
                    0,
                    "{}",
                    "{}",
                    _now_iso(),
                    None,
                    None,
                ),
            )
            self._conn.commit()

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        samples: int = 0,
        per_class: Optional[dict[str, Any]] = None,
        adopted: Optional[dict[str, str]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Transition a run to a terminal state (``completed`` | ``failed``)."""
        with self._lock:
            self._conn.execute(
                _UPDATE_RUN,
                (
                    status,
                    samples,
                    json.dumps(per_class or {}),
                    json.dumps(adopted or {}),
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
            "candidate": row[3],
            "incumbent": row[4],
            "samples": row[5],
            "per_class": json.loads(row[6]),
            "adopted": json.loads(row[7]),
            "started_at": row[8],
            "ended_at": row[9],
            "error": row[10],
        }

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        """Return one run record, or ``None``."""
        row = self._conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM proving_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def latest_run(self) -> Optional[dict[str, Any]]:
        """Return the most recently started run, or ``None``."""
        row = self._conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM proving_runs "
            "ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return self._row_to_record(row) if row else None

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return run records, newest first."""
        rows = self._conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM proving_runs "
            "ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def last_completed_run(self) -> Optional[dict[str, Any]]:
        """Return the most recent run in ``completed`` state, or ``None``."""
        row = self._conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM proving_runs "
            "WHERE status = 'completed' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return self._row_to_record(row) if row else None

    def is_running(self) -> bool:
        """True when a run is in ``running`` state."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM proving_runs WHERE status = 'running'"
        ).fetchone()
        return bool(row and row[0])


__all__ = ["ProvingRunStore"]
