"""Tests for ProvingRunStore — CRUD, status flow, JSON round-trip."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from nova_ai.learning.proving.store import ProvingRunStore


@pytest.fixture()
def store(tmp_path: Path) -> ProvingRunStore:
    s = ProvingRunStore(tmp_path / "runs.db")
    yield s
    s.close()


class TestSchemaAndCrud:
    def test_creates_db_and_table(self, store: ProvingRunStore) -> None:
        assert store.db_path.exists()
        row = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='proving_runs'"
        ).fetchone()
        assert row is not None

    def test_start_and_get_run(self, store: ProvingRunStore) -> None:
        store.start_run("prove_r1", trigger="manual", candidate="c", incumbent="i")
        rec = store.get_run("prove_r1")
        assert rec is not None
        assert rec["id"] == "prove_r1"
        assert rec["status"] == "running"
        assert rec["trigger"] == "manual"
        assert rec["candidate"] == "c"
        assert rec["incumbent"] == "i"
        assert rec["per_class"] == {}
        assert rec["adopted"] == {}
        assert rec["error"] is None

    def test_get_missing_run_returns_none(self, store: ProvingRunStore) -> None:
        assert store.get_run("nope") is None

    def test_finish_completed(self, store: ProvingRunStore) -> None:
        store.start_run("prove_r2", trigger="auto", candidate="c", incumbent="i")
        per_class = {
            "code": {"candidate_acc": 0.9, "incumbent_acc": 0.6, "delta": 0.3,
                     "winner": "c", "total": 10},
        }
        store.finish_run(
            "prove_r2", status="completed", samples=42,
            per_class=per_class, adopted={"code": "c"},
        )
        rec = store.get_run("prove_r2")
        assert rec["status"] == "completed"
        assert rec["samples"] == 42
        assert rec["per_class"]["code"]["delta"] == 0.3
        assert rec["adopted"] == {"code": "c"}
        assert rec["ended_at"] is not None

    def test_finish_failed_with_error(self, store: ProvingRunStore) -> None:
        store.start_run("prove_r3", trigger="manual", candidate="c", incumbent="i")
        store.finish_run("prove_r3", status="failed", error="boom")
        rec = store.get_run("prove_r3")
        assert rec["status"] == "failed"
        assert rec["error"] == "boom"

    def test_json_round_trip_nested(self, store: ProvingRunStore) -> None:
        per_class = {"math": {"delta": -0.05, "winner": None, "total": 5}}
        store.start_run("prove_r4", trigger="scheduled", candidate="a", incumbent="b")
        store.finish_run("prove_r4", status="completed", samples=5, per_class=per_class)
        # Read through a fresh connection/store to prove it's on disk
        store2 = ProvingRunStore(store.db_path)
        try:
            rec = store2.get_run("prove_r4")
            assert rec["per_class"] == per_class
        finally:
            store2.close()


class TestQueries:
    def test_latest_run(self, store: ProvingRunStore) -> None:
        store.start_run("prove_old", trigger="manual", candidate="a", incumbent="b")
        store.start_run("prove_new", trigger="manual", candidate="c", incumbent="d")
        assert store.latest_run()["id"] == "prove_new"

    def test_list_runs_limit_and_order(self, store: ProvingRunStore) -> None:
        for i in range(5):
            store.start_run(f"prove_{i}", trigger="manual", candidate="a", incumbent="b")
        runs = store.list_runs(limit=3)
        assert len(runs) == 3
        assert [r["id"] for r in runs] == ["prove_4", "prove_3", "prove_2"]

    def test_last_completed_run_skips_running(self, store: ProvingRunStore) -> None:
        store.start_run("prove_c1", trigger="manual", candidate="a", incumbent="b")
        store.finish_run("prove_c1", status="completed", samples=10)
        store.start_run("prove_running", trigger="manual", candidate="a", incumbent="b")
        assert store.last_completed_run()["id"] == "prove_c1"

    def test_last_completed_run_none(self, store: ProvingRunStore) -> None:
        assert store.last_completed_run() is None

    def test_is_running(self, store: ProvingRunStore) -> None:
        assert store.is_running() is False
        store.start_run("prove_r", trigger="manual", candidate="a", incumbent="b")
        assert store.is_running() is True
        store.finish_run("prove_r", status="failed", error="x")
        assert store.is_running() is False

    def test_is_running_after_failure(self, store: ProvingRunStore) -> None:
        store.start_run("prove_r", trigger="manual", candidate="a", incumbent="b")
        store.finish_run("prove_r", status="failed", error="x")
        store.start_run("prove_s", trigger="manual", candidate="a", incumbent="b")
        store.finish_run("prove_s", status="completed")
        assert store.is_running() is False


class TestConcurrency:
    def test_threads_share_connection(self, tmp_path: Path) -> None:
        store = ProvingRunStore(tmp_path / "runs.db")
        errors: list[Exception] = []

        def write(i: int) -> None:
            try:
                for j in range(10):
                    rid = f"prove_{i}_{j}"
                    store.start_run(rid, trigger="manual", candidate="a", incumbent="b")
                    store.finish_run(rid, status="completed", samples=j)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        store.close()
        assert not errors
        store2 = ProvingRunStore(tmp_path / "runs.db")
        try:
            assert len(store2.list_runs(limit=100)) == 40
        finally:
            store2.close()
