"""Tests for SyncEngine — checkpoint/resume connector orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional

import pytest

from nova_ai.connectors._stubs import BaseConnector, Document, SyncStatus
from nova_ai.connectors.pipeline import IngestionPipeline
from nova_ai.connectors.store import KnowledgeStore
from nova_ai.connectors.sync_engine import SyncEngine

# ---------------------------------------------------------------------------
# StubConnector test helper
# ---------------------------------------------------------------------------


class StubConnector(BaseConnector):
    """Minimal connector that replays a pre-built list of documents."""

    connector_id = "stub"
    display_name = "Stub"
    auth_type = "filesystem"

    def __init__(self, docs: List[Document]) -> None:
        self._docs = docs

    # BaseConnector abstract methods

    def is_connected(self) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        yield from self._docs

    def sync_status(self) -> SyncStatus:
        return SyncStatus(state="idle", items_synced=len(self._docs))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(
    doc_id: str, source: str = "stub", content: str = "Test content."
) -> Document:
    return Document(
        doc_id=doc_id,
        source=source,
        doc_type="note",
        content=content,
        title=f"Doc {doc_id}",
        author="tester@example.com",
        timestamp=datetime(2025, 3, 1, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> KnowledgeStore:
    return KnowledgeStore(db_path=tmp_path / "knowledge.db")


@pytest.fixture()
def pipeline(store: KnowledgeStore) -> IngestionPipeline:
    return IngestionPipeline(store)


@pytest.fixture()
def engine(pipeline: IngestionPipeline, tmp_path: Path) -> SyncEngine:
    return SyncEngine(pipeline, state_db=str(tmp_path / "sync_state.db"))


# ---------------------------------------------------------------------------
# Test 1: sync_connector — 5 docs from StubConnector all stored
# ---------------------------------------------------------------------------


def test_sync_connector(engine: SyncEngine, store: KnowledgeStore) -> None:
    """StubConnector yields 5 docs; all are ingested and retrievable."""
    docs = [
        _make_doc(f"doc:{i}", content=f"Unique content for document {i}")
        for i in range(5)
    ]
    connector = StubConnector(docs)

    items = engine.sync(connector)

    assert items == 5
    # Each short doc produces exactly one chunk
    assert store.count() == 5


# ---------------------------------------------------------------------------
# Test 2: sync_saves_checkpoint — checkpoint items_synced is correct
# ---------------------------------------------------------------------------


def test_sync_saves_checkpoint(engine: SyncEngine) -> None:
    """After a sync, get_checkpoint returns the correct items_synced count."""
    docs = [_make_doc(f"cp:doc:{i}") for i in range(3)]
    connector = StubConnector(docs)

    engine.sync(connector)

    cp = engine.get_checkpoint("stub")
    assert cp is not None
    assert cp["items_synced"] == 3
    assert cp["last_sync"] is not None
    assert cp["error"] is None


# ---------------------------------------------------------------------------
# Test 3: sync_status_for_unsynced — None for unknown connector
# ---------------------------------------------------------------------------


def test_sync_status_for_unsynced(engine: SyncEngine) -> None:
    """get_checkpoint returns None for a connector that has never been synced."""
    result = engine.get_checkpoint("never_synced_connector")
    assert result is None


# ---------------------------------------------------------------------------
# Test 4: sync_multiple_connectors — filter by source works
# ---------------------------------------------------------------------------


def test_sync_multiple_connectors(
    pipeline: IngestionPipeline, store: KnowledgeStore, tmp_path: Path
) -> None:
    """Two connectors with different sources can be filtered independently."""

    class StubConnectorA(StubConnector):
        connector_id = "stub_a"

    class StubConnectorB(StubConnector):
        connector_id = "stub_b"

    docs_a = [
        _make_doc(f"a:doc:{i}", source="source_a", content=f"Alpha content {i}")
        for i in range(3)
    ]
    docs_b = [
        _make_doc(f"b:doc:{i}", source="source_b", content=f"Beta content {i}")
        for i in range(4)
    ]

    engine = SyncEngine(pipeline, state_db=str(tmp_path / "multi_sync_state.db"))

    items_a = engine.sync(StubConnectorA(docs_a))
    items_b = engine.sync(StubConnectorB(docs_b))

    assert items_a == 3
    assert items_b == 4
    assert store.count() == 7

    # Filter by source: only source_a results
    results_a = store.retrieve("Alpha content", top_k=10, source="source_a")
    assert len(results_a) >= 1
    for r in results_a:
        assert r.metadata.get("source") == "source_a"

    # Filter by source: only source_b results
    results_b = store.retrieve("Beta content", top_k=10, source="source_b")
    assert len(results_b) >= 1
    for r in results_b:
        assert r.metadata.get("source") == "source_b"


# ---------------------------------------------------------------------------
# Cursor checkpointing (regression: current_cursor was assigned once and
# never advanced, so an interrupted sync replayed the whole stream)
# ---------------------------------------------------------------------------


class CursorConnector(BaseConnector):
    """Connector that pages through a fixed document list, advancing a
    public cursor after every yielded document (mirrors how the 8 real
    connectors maintain ``_last_cursor``)."""

    connector_id = "cursor_stub"
    display_name = "Cursor Stub"
    auth_type = "filesystem"

    def __init__(self, docs: List[Document]) -> None:
        self._docs = docs
        self._last_cursor: Optional[str] = None

    def is_connected(self) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        for i, doc in enumerate(self._docs):
            # A resume request restarts after the checkpointed page.
            if cursor is not None and i <= int(cursor):
                continue
            # Publish BEFORE yield so sync_status() reflects the latest
            # yielded doc at any suspension point (engine polls progress
            # while the generator is suspended at yield).
            self._last_cursor = str(i)
            yield doc

    def sync_status(self) -> SyncStatus:
        return SyncStatus(state="idle", cursor=self._last_cursor)


def _make_many_docs(count: int) -> List[Document]:
    return [
        _make_doc(f"cur:doc:{i}", content=f"Cursor page content {i} — unique text")
        for i in range(count)
    ]


def test_interrupted_sync_resumes_from_advanced_cursor(
    pipeline: IngestionPipeline, store: KnowledgeStore, tmp_path: Path
) -> None:
    """A sync that dies mid-stream must checkpoint the last FULLY-INGESTED
    batch cursor so a re-run replays (and dedups) the in-flight batch
    instead of skipping it. Checkpointing the connector's live cursor here
    would skip docs 100-149 (never ingested) — data loss (was 200/250)."""
    engine = SyncEngine(pipeline, state_db=str(tmp_path / "resume_state.db"))
    connector = CursorConnector(_make_many_docs(250))  # > _BATCH_SIZE (100)

    # First run raises after the connector yielded ~150 docs.
    original_sync = connector.sync

    def exploding_sync(**kwargs):  # type: ignore[no-untyped-def]
        yielded = 0
        for doc in original_sync(**kwargs):
            if yielded >= 150:
                raise RuntimeError("boom — sync interrupted mid-page")
            yielded += 1
            yield doc

    connector.sync = exploding_sync  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="interrupted"):
        engine.sync(connector)

    # The checkpoint must be the last fully-ingested batch boundary
    # (docs 0-99 → cursor "99"), NOT the live cursor ("149"): the in-flight
    # batch (100-149) was never ingested and must be replayed on resume.
    cp = engine.get_checkpoint("cursor_stub")
    assert cp is not None
    assert cp["cursor"] == "99", (
        "cursor should be the last ingested batch boundary, got"
        f" {cp['cursor']!r}"
    )

    # Resume: the connector restarts after the saved cursor, so at most
    # ~150 docs are replayed — NOT the full 250.
    connector2 = CursorConnector(_make_many_docs(250))
    connector2._last_cursor = cp["cursor"]
    # Simulate server-side resume semantics: yield only docs past the cursor.
    docs_seen: List[Document] = []

    def resuming_sync(**kwargs):  # type: ignore[no-untyped-def]
        cursor = kwargs.get("cursor")
        for i, doc in enumerate(connector2._docs):
            if cursor is not None and i <= int(cursor):
                continue
            connector2._last_cursor = str(i)
            docs_seen.append(doc)
            yield doc

    connector2.sync = resuming_sync  # type: ignore[method-assign]
    engine.sync(connector2)

    # The dedup pipeline skips already-ingested chunks, so the store ends
    # up with exactly 250 unique chunks and no duplicates.
    assert store.count() == 250


def test_batch_checkpoint_uses_live_connector_cursor(
    pipeline: IngestionPipeline, tmp_path: Path
) -> None:
    """Per-batch checkpoints must persist the cursor the connector reports
    at that moment, not the value captured once before the loop began."""
    engine = SyncEngine(pipeline, state_db=str(tmp_path / "batch_state.db"))
    connector = CursorConnector(_make_many_docs(100))

    seen_checkpoints: List[Optional[str]] = []
    original_save = engine._save_checkpoint

    def spy_save(connector_id, items_synced, *, cursor=None, error=None):  # type: ignore[no-untyped-def]
        seen_checkpoints.append(cursor)
        return original_save(connector_id, items_synced, cursor=cursor, error=error)

    engine._save_checkpoint = spy_save  # type: ignore[method-assign]
    engine.sync(connector)

    # At the final checkpoint the cursor equals the connector's last page
    # index (99), not None.
    assert seen_checkpoints[-1] == "99"
    cp = engine.get_checkpoint("cursor_stub")
    assert cp is not None
    assert cp["cursor"] == "99"
