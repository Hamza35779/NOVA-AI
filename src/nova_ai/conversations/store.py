"""SQLite-backed conversation tree with preference-pair recording.

Unlike the linear chat history (``server/chat_history_store.py``), this
store models a conversation as a **tree of nodes**: every message is a
node with a ``parent_id``, so a fork (or a regenerate) is just a second
child of the same parent. The visible conversation is one root-to-node
path.

Every sibling group created by a fork, a regenerate, or a model race can
be recorded as a **preference pair** — the raw material for the DPO
training lane (``learning.training.dpo``).

Schema mirrors ``TrainingRunStore`` conventions (stdlib ``sqlite3`` in
WAL mode, inline DDL, persistent connection, thread lock around
execute+commit). Lives at ``~/.nova_ai/conversations.db``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CREATE_TABLES = """\
CREATE TABLE IF NOT EXISTS conv_nodes (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    parent_id TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    engine TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    feedback REAL
);
CREATE INDEX IF NOT EXISTS idx_nodes_conversation
    ON conv_nodes(conversation_id);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON conv_nodes(parent_id);
CREATE TABLE IF NOT EXISTS preference_pairs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    prompt_path TEXT NOT NULL,
    chosen_id TEXT NOT NULL,
    rejected_ids TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'fork',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pref_conversation
    ON preference_pairs(conversation_id);
"""

_NODE_COLUMNS = (
    "id, conversation_id, parent_id, role, content, model, engine, "
    "created_at, metadata, feedback"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class ConversationStore:
    """Conversation tree + preference pairs in one SQLite file."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_CREATE_TABLES)
        self._conn.commit()
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    # -- Serialization helpers ------------------------------------------------

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> dict[str, Any]:
        try:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "parent_id": row["parent_id"],
            "role": row["role"],
            "content": row["content"],
            "model": row["model"],
            "engine": row["engine"],
            "created_at": row["created_at"],
            "metadata": metadata,
            "feedback": row["feedback"],
        }

    # -- Conversations --------------------------------------------------------

    def create_conversation(self, title: str = "New conversation") -> dict[str, Any]:
        """Create a conversation (root nodes carry the id as parent_id)."""
        conv_id = _new_id("conv")
        with self._lock:
            self._conn.execute(
                "INSERT INTO conv_nodes (id, conversation_id, parent_id, role, "
                "content, model, engine, created_at, metadata) "
                "VALUES (?, ?, ?, 'system', ?, '', '', ?, ?)",
                (
                    _new_id("root"),
                    conv_id,
                    conv_id,  # roots: parent_id == conversation_id
                    json.dumps({"title": title, "root": True}),
                    _now_iso(),
                    json.dumps({"title": title, "root": True}),
                ),
            )
            self._conn.commit()
        return {"id": conv_id, "title": title, "created_at": _now_iso()}

    def list_conversations(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return conversations (id, title, message count, last activity)."""
        with self._lock:
            roots = self._conn.execute(
                "SELECT conversation_id, metadata, created_at FROM conv_nodes "
                "WHERE role = 'system' AND parent_id = conversation_id"
            ).fetchall()
            counts = {
                row["conversation_id"]: row["node_count"]
                for row in self._conn.execute(
                    "SELECT conversation_id, COUNT(*) AS node_count "
                    "FROM conv_nodes WHERE parent_id != conversation_id "
                    "GROUP BY conversation_id"
                )
            }
            last_ats = {
                row["conversation_id"]: row["last_at"]
                for row in self._conn.execute(
                    "SELECT conversation_id, MAX(created_at) AS last_at "
                    "FROM conv_nodes GROUP BY conversation_id"
                )
            }
        out = []
        for row in roots:
            conv_id = row["conversation_id"]
            try:
                title = (json.loads(row["metadata"]) or {}).get("title", "")
            except (json.JSONDecodeError, TypeError):
                title = ""
            out.append(
                {
                    "id": conv_id,
                    "title": title,
                    "node_count": counts.get(conv_id, 0),
                    "last_at": last_ats.get(conv_id, row["created_at"]),
                }
            )
        out.sort(key=lambda c: c["last_at"], reverse=True)
        return out[:limit]

    # -- Nodes ----------------------------------------------------------------

    def add_message(
        self,
        conversation_id: str,
        parent_id: str,
        role: str,
        content: str,
        *,
        model: str = "",
        engine: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Append a message node under *parent_id*; returns the node id.

        The first user message hangs off the conversation root. Passing
        a different ``parent_id`` creates a sibling (fork/regenerate).
        """
        node_id = _new_id("node")
        with self._lock:
            self._conn.execute(
                "INSERT INTO conv_nodes (id, conversation_id, parent_id, role, "
                "content, model, engine, created_at, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    node_id,
                    conversation_id,
                    parent_id,
                    role,
                    content,
                    model,
                    engine,
                    _now_iso(),
                    json.dumps(metadata or {}),
                ),
            )
            self._conn.commit()
        return node_id

    def get_node(self, node_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_NODE_COLUMNS} FROM conv_nodes WHERE id = ?", (node_id,)
            ).fetchone()
        return self._row_to_node(row) if row else None

    def children(self, node_id: str) -> list[dict[str, Any]]:
        """Children of a node, oldest first (roots: pass the conversation id)."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_NODE_COLUMNS} FROM conv_nodes "
                "WHERE parent_id = ? ORDER BY created_at, id",
                (node_id,),
            ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def path_to_root(self, node_id: str) -> list[dict[str, Any]]:
        """The linearized conversation: node → ... → root (inclusive of node)."""
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        current: Optional[str] = node_id
        while current and current not in seen:
            seen.add(current)
            node = self.get_node(current)
            if node is None:
                break
            if node["role"] == "system" and node["parent_id"] == node["conversation_id"]:
                break  # the root marker is bookkeeping, not a message
            out.append(node)
            current = node["parent_id"]
        out.reverse()
        return out

    def set_feedback(self, node_id: str, score: float) -> bool:
        """Attach a thumbs-style score to a node. True when the node exists."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE conv_nodes SET feedback = ? WHERE id = ?", (score, node_id)
            )
            self._conn.commit()
        return cur.rowcount > 0

    # -- Preference pairs -----------------------------------------------------

    def add_sibling_choice(
        self,
        conversation_id: str,
        prompt_path: list[dict[str, Any]],
        chosen_id: str,
        rejected_ids: list[str],
        *,
        source: str = "fork",
    ) -> str:
        """Record one preference pair (chosen vs rejected siblings).

        ``prompt_path`` is the linearized conversation (dicts with at
        least ``role``/``content``) up to and including the prompt node.
        ``source`` is ``fork`` | ``regen`` | ``race`` | ``thumbs``.
        """
        pair_id = _new_id("pref")
        with self._lock:
            self._conn.execute(
                "INSERT INTO preference_pairs (id, conversation_id, prompt_path, "
                "chosen_id, rejected_ids, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    pair_id,
                    conversation_id,
                    json.dumps(prompt_path, ensure_ascii=False),
                    chosen_id,
                    json.dumps(rejected_ids, ensure_ascii=False),
                    source,
                    _now_iso(),
                ),
            )
            self._conn.commit()
        return pair_id

    def list_preference_pairs(
        self, *, conversation_id: Optional[str] = None, limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Return recorded preference pairs, newest first."""
        with self._lock:
            if conversation_id:
                rows = self._conn.execute(
                    "SELECT * FROM preference_pairs WHERE conversation_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (conversation_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM preference_pairs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        out = []
        for row in rows:
            try:
                prompt_path = json.loads(row["prompt_path"])
                rejected = json.loads(row["rejected_ids"])
            except (json.JSONDecodeError, TypeError):
                continue
            out.append(
                {
                    "id": row["id"],
                    "conversation_id": row["conversation_id"],
                    "prompt_path": prompt_path,
                    "chosen_id": row["chosen_id"],
                    "rejected_ids": rejected,
                    "source": row["source"],
                    "created_at": row["created_at"],
                }
            )
        return out

    def count_preference_pairs(self) -> int:
        with self._lock:
            (count,) = self._conn.execute(
                "SELECT COUNT(*) FROM preference_pairs"
            ).fetchone()
        return int(count)


__all__ = ["ConversationStore"]
