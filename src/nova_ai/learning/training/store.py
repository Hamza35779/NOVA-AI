"""SQLite-backed storage for self-training run records.

Mirrors ``SessionStore`` conventions (stdlib ``sqlite3`` in WAL mode,
inline DDL, persistent connection). Lives at
``~/.nova_ai/learning/training/runs.db`` — separate file from the
spec-search SessionStore and the OptimizationStore.

``nova train status`` / ``nova train list`` read from here, and the
auto-trigger counts new qualifying traces since the last successful run.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CREATE_RUNS = """\
CREATE TABLE IF NOT EXISTS training_runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'manual',
    base_model TEXT NOT NULL DEFAULT '',
    pairs INTEGER NOT NULL DEFAULT 0,
    avg_loss REAL,
    adapter_path TEXT,
    deploy_results TEXT NOT NULL DEFAULT '[]',
    benchmark_before REAL,
    benchmark_after REAL,
    benchmark_delta REAL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    error TEXT
);
"""

# Lane column (sft | dpo) added after the table shipped; ALTER for older DBs.
_MIGRATE_LANE = "ALTER TABLE training_runs ADD COLUMN lane TEXT NOT NULL DEFAULT 'sft'"

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_runs_started_at ON training_runs(started_at)",
    "CREATE INDEX IF NOT EXISTS idx_runs_status ON training_runs(status)",
]

_INSERT_RUN = """\
INSERT OR REPLACE INTO training_runs (
    id, status, trigger, base_model, pairs, avg_loss, adapter_path,
    deploy_results, benchmark_before, benchmark_after, benchmark_delta,
    started_at, ended_at, error, lane
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_UPDATE_RUN = """\
UPDATE training_runs SET
    status = ?, pairs = ?, avg_loss = ?, adapter_path = ?,
    deploy_results = ?, benchmark_before = ?, benchmark_after = ?,
    benchmark_delta = ?, ended_at = ?, error = ?
WHERE id = ?
"""

_RUN_COLUMNS = (
    "id, status, trigger, base_model, pairs, avg_loss, adapter_path, "
    "deploy_results, benchmark_before, benchmark_after, benchmark_delta, "
    "started_at, ended_at, error, lane"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrainingRunStore:
    """SQLite-backed store for training run records."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_RUNS)
        for idx in _CREATE_INDEXES:
            self._conn.execute(idx)
        # Older DBs predate the lane column (sft | dpo).
        cols = {
            row[1] for row in self._conn.execute("PRAGMA table_info(training_runs)")
        }
        if "lane" not in cols:
            self._conn.execute(_MIGRATE_LANE)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- Write API -----------------------------------------------------------

    def start_run(
        self,
        run_id: str,
        *,
        trigger: str = "manual",
        base_model: str = "",
        lane: str = "sft",
    ) -> None:
        """Record a new run in ``running`` state."""
        self._conn.execute(
            _INSERT_RUN,
            (
                run_id,
                "running",
                trigger,
                base_model,
                0,
                None,
                None,
                "[]",
                None,
                None,
                None,
                _now_iso(),
                None,
                None,
                lane,
            ),
        )
        self._conn.commit()

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        pairs: int = 0,
        avg_loss: Optional[float] = None,
        adapter_path: Optional[str] = None,
        deploy_results: Optional[list[dict[str, Any]]] = None,
        benchmark_before: Optional[float] = None,
        benchmark_after: Optional[float] = None,
        benchmark_delta: Optional[float] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update a run to a terminal state.

        Status values: ``completed``, ``rolled_back``, ``failed``,
        ``pending_review``, ``running`` (for heartbeat-style updates).
        """
        self._conn.execute(
            _UPDATE_RUN,
            (
                status,
                pairs,
                avg_loss,
                adapter_path,
                json.dumps(deploy_results or [], indent=2),
                benchmark_before,
                benchmark_after,
                benchmark_delta,
                _now_iso(),
                error,
                run_id,
            ),
        )
        self._conn.commit()

    # -- Read API ------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": row[0],
            "status": row[1],
            "trigger": row[2],
            "base_model": row[3],
            "pairs": row[4],
            "avg_loss": row[5],
            "adapter_path": row[6],
            "deploy_results": json.loads(row[7]) if row[7] else [],
            "benchmark_before": row[8],
            "benchmark_after": row[9],
            "benchmark_delta": row[10],
            "started_at": row[11],
            "ended_at": row[12],
            "error": row[13],
            "lane": row[14] if len(row) > 14 else "sft",
        }

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        """Return one run record, or None."""
        cur = self._conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM training_runs WHERE id = ?", (run_id,)
        )
        row = cur.fetchone()
        return self._row_to_dict(row) if row else None

    def latest_run(self) -> Optional[dict[str, Any]]:
        """Return the most recently started run, or None."""
        cur = self._conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM training_runs "
            "ORDER BY started_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        return self._row_to_dict(row) if row else None

    def list_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent runs, newest first."""
        cur = self._conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM training_runs "
            "ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_dict(row) for row in cur.fetchall()]

    def last_successful_run(self) -> Optional[dict[str, Any]]:
        """Return the most recent ``completed`` run, or None."""
        cur = self._conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM training_runs "
            "WHERE status = 'completed' ORDER BY started_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        return self._row_to_dict(row) if row else None

    def is_running(self) -> bool:
        """True if any run is currently in ``running`` state."""
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM training_runs WHERE status = 'running'"
        )
        (count,) = cur.fetchone()
        return count > 0


__all__ = ["TrainingRunStore"]
