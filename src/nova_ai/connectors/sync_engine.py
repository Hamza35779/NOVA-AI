"""SyncEngine — checkpoint/resume orchestration for connector syncs.

Wraps ``IngestionPipeline`` with a lightweight SQLite state database so that
long-running syncs can be interrupted and resumed from the last saved cursor.

Typical usage::

    store = KnowledgeStore(db_path=":memory:")
    pipeline = IngestionPipeline(store)
    engine = SyncEngine(pipeline)

    items = engine.sync(connector)        # first run
    items = engine.sync(connector)        # resumes from saved cursor
    cp = engine.get_checkpoint(connector.connector_id)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from nova_ai.connectors._stubs import BaseConnector
from nova_ai.connectors.pipeline import IngestionPipeline
from nova_ai.core.config import DEFAULT_CONFIG_DIR

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS sync_state (
    connector_id  TEXT PRIMARY KEY,
    items_synced  INTEGER NOT NULL DEFAULT 0,
    cursor        TEXT,
    last_sync     TEXT,
    error         TEXT
);
"""

_BATCH_SIZE = 100


class SyncEngine:
    """Orchestrate connector syncs with checkpoint/resume tracking.

    Parameters
    ----------
    pipeline:
        The ``IngestionPipeline`` that documents are fed into.
    state_db:
        Path to the SQLite database used for checkpoint state.  If empty,
        defaults to ``DEFAULT_CONFIG_DIR / "sync_state.db"``.
    """

    def __init__(self, pipeline: IngestionPipeline, *, state_db: str = "") -> None:
        self._pipeline = pipeline

        if not state_db:
            db_path = DEFAULT_CONFIG_DIR / "sync_state.db"
        else:
            db_path = Path(state_db)

        # Ensure parent directory exists (skip for :memory:)
        if str(db_path) != ":memory:":
            db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA busy_timeout=30000;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.execute(_CREATE_STATE_TABLE)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync(self, connector: BaseConnector) -> int:
        """Run a full sync for *connector* and return the number of items ingested.

        Resumes from the last saved cursor if one exists.  Documents are
        batched in groups of 100 before being handed to the pipeline; a
        checkpoint is saved after every batch and once more at the end.

        The checkpointed cursor is refreshed after every successful batch by
        polling ``connector.sync_status().cursor`` — connectors advance their
        internal ``_last_cursor`` as they page through the source, so an
        interrupted sync resumes from the last *completed* page instead of
        replaying the whole stream.  Connectors that don't track a cursor
        report ``None`` here; their checkpoints then fall back to the
        ``since`` timestamp semantics (the value stays ``None`` and the
        last_sync timestamp does the filtering).

        On error the *last successful* cursor is kept, deliberately not the
        connector's live one: mid-batch failures leave the live cursor ahead
        of the ingested boundary, and checkpointing it would skip the
        in-flight documents.  Replaying from the last good cursor is safe —
        ingestion is idempotent (``INSERT OR IGNORE`` on the natural key).

        On error the checkpoint is updated with the error message and the
        exception is re-raised so callers can handle it.
        """
        connector_id: str = connector.connector_id

        # Load any previous checkpoint so we can resume.
        checkpoint = self.get_checkpoint(connector_id)
        prior_cursor: Optional[str] = checkpoint["cursor"] if checkpoint else None
        prior_items: int = checkpoint["items_synced"] if checkpoint else 0

        since: Optional[datetime] = None
        if checkpoint and checkpoint.get("last_sync"):
            try:
                since = datetime.fromisoformat(checkpoint["last_sync"])
            except (ValueError, TypeError):
                pass

        items_ingested = 0
        current_cursor: Optional[str] = prior_cursor

        def _latest_cursor() -> Optional[str]:
            """Current cursor reported by the connector, if it tracks one."""
            try:
                return connector.sync_status().cursor
            except Exception:  # noqa: BLE001 — progress polling is best-effort
                return current_cursor

        try:
            doc_iter = connector.sync(since=since, cursor=prior_cursor)

            batch = []
            for doc in doc_iter:
                batch.append(doc)

                if len(batch) >= _BATCH_SIZE:
                    items_ingested += self._pipeline.ingest(batch)
                    batch = []
                    current_cursor = _latest_cursor()
                    self._save_checkpoint(
                        connector_id,
                        prior_items + items_ingested,
                        cursor=current_cursor,
                    )

            # Ingest any remaining documents.
            if batch:
                items_ingested += self._pipeline.ingest(batch)
                current_cursor = _latest_cursor()

        except Exception as exc:
            # Checkpoint the LAST SUCCESSFUL batch cursor, not the connector's
            # live cursor: at failure time the live cursor is ahead of the
            # ingested boundary (the in-flight batch was never ingested), and
            # checkpointing it would skip those documents on resume (data
            # loss — reproduced as 200/250 chunks). Replaying from the last
            # good cursor is safe: ingestion is idempotent.
            self._save_checkpoint(
                connector_id,
                prior_items + items_ingested,
                cursor=current_cursor,
                error=str(exc),
            )
            raise

        # Final checkpoint — clear any previous error.
        self._save_checkpoint(
            connector_id,
            prior_items + items_ingested,
            cursor=current_cursor,
            error=None,
        )
        return items_ingested

    def get_checkpoint(self, connector_id: str) -> Optional[Dict[str, Any]]:
        """Return the last checkpoint, or ``None`` if never synced."""
        sql = (
            "SELECT items_synced, cursor, last_sync, error"
            " FROM sync_state WHERE connector_id = ?"
        )
        row = self._conn.execute(sql, (connector_id,)).fetchone()

        if row is None:
            return None

        return {
            "items_synced": row["items_synced"],
            "cursor": row["cursor"],
            "last_sync": row["last_sync"],
            "error": row["error"],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _save_checkpoint(
        self,
        connector_id: str,
        items_synced: int,
        *,
        cursor: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """UPSERT a checkpoint row into the state database."""
        now = datetime.now(tz=timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO sync_state
                (connector_id, items_synced, cursor, last_sync, error)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(connector_id) DO UPDATE SET
                items_synced = excluded.items_synced,
                cursor       = excluded.cursor,
                last_sync    = excluded.last_sync,
                error        = excluded.error
            """,
            (connector_id, items_synced, cursor, now, error),
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the state DB (required for Windows temp-dir cleanup, B4)."""
        try:
            self._conn.commit()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass


__all__ = ["SyncEngine"]
