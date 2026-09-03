"""SQLite-backed stores for memory consolidation.

Two databases live under ``~/.nova_ai/learning/consolidation/``:

- ``facts.db`` — the distilled fact base (``FactStore``)
- ``runs.db``  — consolidation run history (``ConsolidationRunStore``)

Both mirror ``ProvingRunStore`` conventions: stdlib ``sqlite3`` in WAL
mode, inline DDL, a single persistent connection shared across threads
with a lock serializing execute+commit pairs.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fact store
# ---------------------------------------------------------------------------

_CREATE_FACTS = """\
CREATE TABLE IF NOT EXISTS facts (
    id               TEXT PRIMARY KEY,
    content          TEXT NOT NULL,
    topic            TEXT NOT NULL DEFAULT '',
    source_trace_ids TEXT NOT NULL DEFAULT '[]',
    session_ids      TEXT NOT NULL DEFAULT '[]',
    confidence       REAL NOT NULL DEFAULT 0.5,
    status           TEXT NOT NULL DEFAULT 'active',
    first_seen       REAL NOT NULL,
    last_seen        REAL NOT NULL,
    superseded_by    TEXT
);
"""

_CREATE_FACT_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_facts_status ON facts(status)",
    "CREATE INDEX IF NOT EXISTS idx_facts_topic ON facts(topic)",
]

_FACT_COLUMNS = (
    "id, content, topic, source_trace_ids, session_ids, confidence, "
    "status, first_seen, last_seen, superseded_by"
)


def _now() -> float:
    return time.time()


def _new_fact_id() -> str:
    return f"fact_{uuid.uuid4().hex[:12]}"


class FactStore:
    """SQLite-backed store of atomic facts distilled from traces."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_FACTS)
        for idx in _CREATE_FACT_INDEXES:
            self._conn.execute(idx)
        self._conn.commit()
        # One shared connection across threads: serialize execute+commit.
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- Write API -----------------------------------------------------------

    def add_fact(
        self,
        content: str,
        *,
        topic: str = "",
        confidence: float = 0.5,
        source_trace_ids: Optional[list[str]] = None,
        session_ids: Optional[list[str]] = None,
        now: Optional[float] = None,
    ) -> str:
        """Insert a new active fact and return its id."""
        fact_id = _new_fact_id()
        ts = now if now is not None else _now()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO facts ("
                "id, content, topic, source_trace_ids, session_ids, "
                "confidence, status, first_seen, last_seen, superseded_by"
                ") VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, NULL)",
                (
                    fact_id,
                    content,
                    topic,
                    json.dumps(source_trace_ids or []),
                    json.dumps(session_ids or []),
                    float(confidence),
                    ts,
                    ts,
                ),
            )
            self._conn.commit()
        return fact_id

    def supersede(self, fact_id: str, *, by_id: str) -> bool:
        """Mark *fact_id* superseded by *by_id*. Returns True when found."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE facts SET status = 'superseded', superseded_by = ? "
                "WHERE id = ? AND status = 'active'",
                (by_id, fact_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def touch(self, fact_id: str, *, now: Optional[float] = None) -> bool:
        """Refresh ``last_seen`` for *fact_id* (re-confirmed evidence)."""
        ts = now if now is not None else _now()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE facts SET last_seen = ? WHERE id = ?",
                (ts, fact_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def decay(self, *, older_than_days: float) -> int:
        """Mark active facts untouched for *older_than_days* as decayed."""
        cutoff = _now() - older_than_days * 86400.0
        with self._lock:
            cur = self._conn.execute(
                "UPDATE facts SET status = 'decayed' "
                "WHERE status = 'active' AND last_seen < ?",
                (cutoff,),
            )
            self._conn.commit()
        return cur.rowcount

    def set_status(self, fact_id: str, status: str) -> bool:
        """Force a status (manual forget/re-activate path)."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE facts SET status = ? WHERE id = ?",
                (status, fact_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

    # -- Read API ------------------------------------------------------------

    @staticmethod
    def _row_to_fact(row: tuple) -> dict[str, Any]:
        return {
            "id": row[0],
            "content": row[1],
            "topic": row[2],
            "source_trace_ids": json.loads(row[3]),
            "session_ids": json.loads(row[4]),
            "confidence": row[5],
            "status": row[6],
            "first_seen": row[7],
            "last_seen": row[8],
            "superseded_by": row[9],
        }

    def get_fact(self, fact_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            f"SELECT {_FACT_COLUMNS} FROM facts WHERE id = ?", (fact_id,)
        ).fetchone()
        return self._row_to_fact(row) if row else None

    def list_facts(
        self,
        *,
        status: Optional[str] = "active",
        topic: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Facts newest-first, optionally filtered by status and topic."""
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if topic is not None:
            clauses.append("topic = ?")
            params.append(topic)
        where = " AND ".join(clauses) if clauses else "1=1"
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT {_FACT_COLUMNS} FROM facts WHERE {where} "
            "ORDER BY last_seen DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def active_facts(self) -> list[dict[str, Any]]:
        """All active facts, highest confidence first."""
        rows = self._conn.execute(
            f"SELECT {_FACT_COLUMNS} FROM facts WHERE status = 'active' "
            "ORDER BY confidence DESC, last_seen DESC"
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def export_core(self, max_chars: int) -> list[dict[str, Any]]:
        """Active facts packed under a character budget.

        Ordered by confidence (desc) then recency; a fact that would push
        the total past *max_chars* is skipped (not truncated), and packing
        continues so long facts never evict the whole block.
        """
        packed: list[dict[str, Any]] = []
        budget = max(max_chars, 0)
        for fact in self.active_facts():
            cost = len(fact["content"]) + 2  # "- " prefix + newline
            if cost > budget:
                continue
            packed.append(fact)
            budget -= cost
        return packed

    def count(self, *, status: Optional[str] = None) -> int:
        if status is None:
            row = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM facts WHERE status = ?", (status,)
            ).fetchone()
        return row[0] if row else 0


# ---------------------------------------------------------------------------
# Run store
# ---------------------------------------------------------------------------

_CREATE_RUNS = """\
CREATE TABLE IF NOT EXISTS consolidation_runs (
    id        TEXT PRIMARY KEY,
    status    TEXT NOT NULL,
    trigger   TEXT NOT NULL DEFAULT 'manual',
    summary   TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    ended_at  TEXT,
    error     TEXT
);
"""

_INSERT_RUN = """\
INSERT OR REPLACE INTO consolidation_runs (
    id, status, trigger, summary, started_at, ended_at, error
) VALUES (?, ?, ?, '{}', ?, NULL, NULL)
"""

_UPDATE_RUN = """\
UPDATE consolidation_runs SET
    status = ?, summary = ?, ended_at = ?, error = ?
WHERE id = ?
"""

_RUN_COLUMNS = "id, status, trigger, summary, started_at, ended_at, error"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConsolidationRunStore:
    """SQLite-backed store for consolidation run records."""

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

    def start_run(self, run_id: str, *, trigger: str = "manual") -> None:
        with self._lock:
            self._conn.execute(_INSERT_RUN, (run_id, "running", trigger, _now_iso()))
            self._conn.commit()

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        summary: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                _UPDATE_RUN,
                (status, json.dumps(summary or {}), _now_iso(), error, run_id),
            )
            self._conn.commit()

    @staticmethod
    def _row_to_record(row: tuple) -> dict[str, Any]:
        return {
            "id": row[0],
            "status": row[1],
            "trigger": row[2],
            "summary": json.loads(row[3]),
            "started_at": row[4],
            "ended_at": row[5],
            "error": row[6],
        }

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM consolidation_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def latest_run(self) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM consolidation_runs "
            "ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return self._row_to_record(row) if row else None

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM consolidation_runs "
            "ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def is_running(self) -> bool:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM consolidation_runs WHERE status = 'running'"
        ).fetchone()
        return bool(row and row[0])


__all__ = ["ConsolidationRunStore", "FactStore"]
