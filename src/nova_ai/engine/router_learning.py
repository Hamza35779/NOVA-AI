"""Router Learning — records routing decisions and feedback to improve tier classification.

Uses a lightweight SQLite store so corrections persist across restarts.
No ML library required — corrections are applied as weighted adjustments
to the heuristic score based on past human feedback.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from nova_ai.core.paths import get_config_dir

logger = logging.getLogger(__name__)

_DB_NAME = "router_feedback.db"

# Threshold: if a query pattern has been corrected this many times,
# its correction is applied with full confidence.
_CONFIDENCE_THRESHOLD = 3


def _query_hash(content: str) -> str:
    """Produce a short stable hash for a query's content."""
    # Use first 200 chars for fingerprinting — captures topic without noise.
    normalized = " ".join(content.lower().split())[:200]
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


class RoutingFeedbackStore:
    """Thread-safe SQLite store for routing decisions and user feedback."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or (get_config_dir() / "optimizer" / _DB_NAME)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS routing_decisions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id  TEXT NOT NULL,
                    query_hash  TEXT NOT NULL,
                    tier_chosen TEXT NOT NULL,
                    latency_ms  REAL DEFAULT 0,
                    timestamp   REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS routing_feedback (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id      TEXT NOT NULL,
                    query_hash      TEXT NOT NULL,
                    tier_chosen     TEXT NOT NULL,
                    correct_tier    TEXT NOT NULL,
                    timestamp       REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_decisions_hash ON routing_decisions(query_hash);
                CREATE INDEX IF NOT EXISTS idx_feedback_hash  ON routing_feedback(query_hash);
            """)

    def record_decision(
        self,
        message_id: str,
        query_content: str,
        tier_chosen: str,
        latency_ms: float = 0.0,
    ) -> None:
        """Record a routing decision for a message."""
        qhash = _query_hash(query_content)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO routing_decisions (message_id, query_hash, tier_chosen, latency_ms, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (message_id, qhash, tier_chosen, latency_ms, time.time()),
            )

    def record_feedback(
        self,
        message_id: str,
        query_content: str,
        tier_chosen: str,
        correct_tier: str,
    ) -> None:
        """Record that a routing decision was wrong and the correct tier."""
        if tier_chosen == correct_tier:
            return
        qhash = _query_hash(query_content)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO routing_feedback (message_id, query_hash, tier_chosen, correct_tier, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (message_id, qhash, tier_chosen, correct_tier, time.time()),
            )
        logger.info(
            "Router feedback: message=%s tier=%s -> correct=%s (hash=%s)",
            message_id, tier_chosen, correct_tier, qhash,
        )

    def record_implicit_feedback(
        self,
        message_id: str,
        query_content: str,
        tier_chosen: str,
        thumbs_up: bool,
    ) -> None:
        """Derive a correction from a thumbs-up/down signal.

        Thumbs-down on a 'small' response → should have been 'medium'.
        Thumbs-up on any response → reinforce (no correction needed).
        """
        if thumbs_up:
            return  # Positive signal — current tier was good

        # Negative signal — suggest the next tier up
        upgrade = {"small": "medium", "medium": "large"}.get(tier_chosen)
        if upgrade:
            self.record_feedback(message_id, query_content, tier_chosen, upgrade)

    def get_correction(
        self, query_content: str, heuristic_tier: str
    ) -> Optional[str]:
        """Look up learned correction for a query hash.

        Returns the corrected tier if confidence threshold is met, else None.
        """
        qhash = _query_hash(query_content)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT correct_tier, COUNT(*) as cnt "
                "FROM routing_feedback "
                "WHERE query_hash = ? AND tier_chosen = ? "
                "GROUP BY correct_tier "
                "ORDER BY cnt DESC LIMIT 1",
                (qhash, heuristic_tier),
            ).fetchone()

        if rows and rows["cnt"] >= _CONFIDENCE_THRESHOLD:
            return rows["correct_tier"]
        return None

    def get_stats(self) -> dict:
        """Return aggregate statistics about the feedback store."""
        with self._lock, self._connect() as conn:
            total_decisions = conn.execute("SELECT COUNT(*) FROM routing_decisions").fetchone()[0]
            total_feedback = conn.execute("SELECT COUNT(*) FROM routing_feedback").fetchone()[0]
            corrections_by_tier = {
                row["tier_chosen"]: row["cnt"]
                for row in conn.execute(
                    "SELECT tier_chosen, COUNT(*) as cnt FROM routing_feedback GROUP BY tier_chosen"
                ).fetchall()
            }
        return {
            "total_decisions": total_decisions,
            "total_feedback": total_feedback,
            "corrections_by_tier": corrections_by_tier,
        }


# ── Global singleton ────────────────────────────────────────────

_store: Optional[RoutingFeedbackStore] = None
_store_lock = threading.Lock()


def get_feedback_store() -> RoutingFeedbackStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = RoutingFeedbackStore()
    return _store


__all__ = ["RoutingFeedbackStore", "get_feedback_store", "_query_hash"]
