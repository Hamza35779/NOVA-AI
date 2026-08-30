"""SQLite-backed chat history store with full-text search.

Stores conversations and messages persistently across sessions.
Uses FTS5 for fast full-text search across message content.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from nova_ai.core.paths import get_config_dir

logger = logging.getLogger(__name__)

_DB_FILE = "chat_history.db"


class ChatHistoryStore:
    """Thread-safe SQLite store for chat conversations and messages."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or (get_config_dir() / _DB_FILE)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id          TEXT PRIMARY KEY,
                    title       TEXT NOT NULL DEFAULT 'New conversation',
                    created_at  REAL NOT NULL,
                    last_active REAL NOT NULL,
                    pinned      INTEGER NOT NULL DEFAULT 0,
                    message_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_conv_last_active ON conversations(last_active DESC);
                CREATE INDEX IF NOT EXISTS idx_conv_pinned ON conversations(pinned DESC, last_active DESC);

                CREATE TABLE IF NOT EXISTS messages (
                    id          TEXT PRIMARY KEY,
                    conv_id     TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role        TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    tool_calls  TEXT,
                    timestamp   REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conv_id, timestamp);

                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content,
                    conv_id UNINDEXED,
                    msg_id UNINDEXED,
                    role UNINDEXED,
                    timestamp UNINDEXED
                );

                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
            """)
            self._conn.commit()

    # ── Conversations ─────────────────────────────────────────

    def create_conversation(self, title: str = "New conversation") -> dict:
        conv_id = str(uuid.uuid4())
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO conversations (id, title, created_at, last_active) VALUES (?, ?, ?, ?)",
                (conv_id, title, now, now),
            )
            self._conn.commit()
        return {"id": conv_id, "title": title, "created_at": now, "last_active": now, "pinned": False, "message_count": 0}

    def list_conversations(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM conversations ORDER BY pinned DESC, last_active DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_conversation(self, conv_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
        return dict(row) if row else None

    def update_conversation(self, conv_id: str, title: Optional[str] = None, pinned: Optional[bool] = None) -> Optional[dict]:
        fields = []
        values = []
        if title is not None:
            fields.append("title = ?")
            values.append(title)
        if pinned is not None:
            fields.append("pinned = ?")
            values.append(1 if pinned else 0)
        if not fields:
            return self.get_conversation(conv_id)
        values.append(conv_id)
        with self._lock:
            self._conn.execute(f"UPDATE conversations SET {', '.join(fields)} WHERE id = ?", values)
            self._conn.commit()
        return self.get_conversation(conv_id)

    def delete_conversation(self, conv_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            self._conn.execute("DELETE FROM messages_fts WHERE conv_id = ?", (conv_id,))
            self._conn.commit()
        return cur.rowcount > 0

    # ── Messages ──────────────────────────────────────────────

    def add_message(
        self,
        conv_id: str,
        role: str,
        content: str,
        tool_calls: Optional[Any] = None,
    ) -> dict:
        msg_id = str(uuid.uuid4())
        now = time.time()
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages (id, conv_id, role, content, tool_calls, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (msg_id, conv_id, role, content, tool_calls_json, now),
            )
            self._conn.execute(
                "UPDATE conversations SET last_active = ?, message_count = message_count + 1 WHERE id = ?",
                (now, conv_id),
            )
            self._conn.execute(
                "INSERT INTO messages_fts (content, conv_id, msg_id, role, timestamp) VALUES (?, ?, ?, ?, ?)",
                (content, conv_id, msg_id, role, now),
            )
            self._conn.commit()
        return {"id": msg_id, "conv_id": conv_id, "role": role, "content": content, "timestamp": now}

    def get_messages(self, conv_id: str, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE conv_id = ? ORDER BY timestamp ASC LIMIT ?",
                (conv_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Search ────────────────────────────────────────────────

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search across all message content."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT f.conv_id, f.msg_id, f.role, f.timestamp, snippet(messages_fts, 0, '<b>', '</b>', '...', 20) as snippet
                   FROM messages_fts f
                   WHERE messages_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
        return [dict(r) for r in rows]


# ── Singleton ─────────────────────────────────────────────────

_store: Optional[ChatHistoryStore] = None
_lock = threading.Lock()


def get_history_store() -> ChatHistoryStore:
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                _store = ChatHistoryStore()
    return _store
