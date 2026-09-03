"""Tests for the memory-consolidation fact store and run store."""

from __future__ import annotations

import threading

import pytest

from nova_ai.memory.consolidation.store import ConsolidationRunStore, FactStore


@pytest.fixture()
def fact_store(tmp_path):
    s = FactStore(tmp_path / "facts.db")
    yield s
    s.close()


@pytest.fixture()
def run_store(tmp_path):
    s = ConsolidationRunStore(tmp_path / "runs.db")
    yield s
    s.close()


class TestFactStoreCRUD:
    def test_add_and_get(self, fact_store: FactStore) -> None:
        fid = fact_store.add_fact("The user prefers dark mode", topic="style",
                                  confidence=0.9)
        fact = fact_store.get_fact(fid)
        assert fact is not None
        assert fact["content"] == "The user prefers dark mode"
        assert fact["topic"] == "style"
        assert fact["confidence"] == pytest.approx(0.9)
        assert fact["status"] == "active"
        assert fact["superseded_by"] is None

    def test_add_fact_records_provenance(self, fact_store: FactStore) -> None:
        fid = fact_store.add_fact(
            "Deploys on Fridays", source_trace_ids=["t1", "t2"],
            session_ids=["s1"],
        )
        fact = fact_store.get_fact(fid)
        assert fact["source_trace_ids"] == ["t1", "t2"]
        assert fact["session_ids"] == ["s1"]

    def test_get_missing_returns_none(self, fact_store: FactStore) -> None:
        assert fact_store.get_fact("fact_nope") is None

    def test_list_filters_by_status(self, fact_store: FactStore) -> None:
        a = fact_store.add_fact("Fact A")
        fact_store.add_fact("Fact B")
        fact_store.set_status(a, "forgotten")
        active = fact_store.list_facts(status="active")
        assert [f["content"] for f in active] == ["Fact B"]
        all_facts = fact_store.list_facts(status=None)
        assert len(all_facts) == 2

    def test_list_filters_by_topic(self, fact_store: FactStore) -> None:
        fact_store.add_fact("Fact A", topic="editor")
        fact_store.add_fact("Fact B", topic="deploy")
        topics = {f["topic"] for f in fact_store.list_facts(topic="editor")}
        assert topics == {"editor"}

    def test_supersede(self, fact_store: FactStore) -> None:
        old = fact_store.add_fact("Uses vim", confidence=0.8)
        new = fact_store.add_fact("Uses nvim", confidence=0.9)
        assert fact_store.supersede(old, by_id=new) is True
        assert fact_store.get_fact(old)["status"] == "superseded"
        assert fact_store.get_fact(old)["superseded_by"] == new

    def test_supersede_missing_returns_false(self, fact_store: FactStore) -> None:
        assert fact_store.supersede("fact_nope", by_id="fact_x") is False

    def test_touch_updates_last_seen(self, fact_store: FactStore) -> None:
        fid = fact_store.add_fact("Fact", now=1000.0)
        assert fact_store.touch(fid, now=2000.0) is True
        assert fact_store.get_fact(fid)["last_seen"] == 2000.0

    def test_decay_marks_stale_active_only(self, fact_store: FactStore) -> None:
        stale = fact_store.add_fact("Stale", now=0.0)
        fresh = fact_store.add_fact("Fresh", now=2_000_000_000.0)
        dead = fact_store.add_fact("Dead", now=0.0)
        fact_store.set_status(dead, "superseded")
        n = fact_store.decay(older_than_days=10)
        assert n == 1
        assert fact_store.get_fact(stale)["status"] == "decayed"
        assert fact_store.get_fact(fresh)["status"] == "active"
        assert fact_store.get_fact(dead)["status"] == "superseded"

    def test_count(self, fact_store: FactStore) -> None:
        fact_store.add_fact("A")
        fact_store.add_fact("B")
        assert fact_store.count() == 2
        assert fact_store.count(status="active") == 2


class TestCorePacking:
    def test_export_core_orders_by_confidence(self, fact_store: FactStore) -> None:
        fact_store.add_fact("Low conf fact", confidence=0.3)
        fact_store.add_fact("High conf fact", confidence=0.9)
        core = fact_store.export_core(max_chars=10_000)
        assert core[0]["content"] == "High conf fact"

    def test_export_core_respects_budget(self, fact_store: FactStore) -> None:
        fact_store.add_fact("x" * 100, confidence=0.9)
        fact_store.add_fact("y" * 30, confidence=0.8)
        core = fact_store.export_core(max_chars=50)
        assert [f["content"] for f in core] == ["y" * 30]

    def test_export_core_skips_oversized_but_continues(
        self, fact_store: FactStore
    ) -> None:
        fact_store.add_fact("huge" * 50, confidence=0.95)
        fact_store.add_fact("tiny", confidence=0.5)
        core = fact_store.export_core(max_chars=100)
        assert [f["content"] for f in core] == ["tiny"]

    def test_export_core_excludes_non_active(self, fact_store: FactStore) -> None:
        fid = fact_store.add_fact("Gone", confidence=0.99)
        fact_store.set_status(fid, "decayed")
        assert fact_store.export_core(max_chars=1000) == []

    def test_export_core_empty_store(self, fact_store: FactStore) -> None:
        assert fact_store.export_core(max_chars=1000) == []


class TestRunStore:
    def test_start_and_finish(self, run_store: ConsolidationRunStore) -> None:
        run_store.start_run("consol_1", trigger="scheduled")
        run_store.finish_run(
            "consol_1", status="completed",
            summary={"facts_added": 3},
        )
        run = run_store.get_run("consol_1")
        assert run["status"] == "completed"
        assert run["trigger"] == "scheduled"
        assert run["summary"] == {"facts_added": 3}
        assert run["ended_at"] is not None

    def test_latest_run(self, run_store: ConsolidationRunStore) -> None:
        run_store.start_run("consol_1")
        run_store.start_run("consol_2")
        assert run_store.latest_run()["id"] == "consol_2"

    def test_list_runs_order_and_limit(self, run_store: ConsolidationRunStore) -> None:
        for i in range(5):
            run_store.start_run(f"consol_{i}")
        runs = run_store.list_runs(limit=3)
        assert [r["id"] for r in runs] == ["consol_4", "consol_3", "consol_2"]

    def test_is_running(self, run_store: ConsolidationRunStore) -> None:
        assert run_store.is_running() is False
        run_store.start_run("consol_1")
        assert run_store.is_running() is True
        run_store.finish_run("consol_1", status="failed", error="boom")
        assert run_store.is_running() is False

    def test_failed_run_round_trip(self, run_store: ConsolidationRunStore) -> None:
        run_store.start_run("consol_9")
        run_store.finish_run("consol_9", status="failed", error="no traces")
        assert run_store.get_run("consol_9")["error"] == "no traces"

    def test_threads_share_connection(self, tmp_path) -> None:
        store = ConsolidationRunStore(tmp_path / "runs.db")
        try:
            def worker(i: int) -> None:
                store.start_run(f"consol_{i}")
                store.finish_run(f"consol_{i}", status="completed")

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert len(store.list_runs(limit=20)) == 8
        finally:
            store.close()


class TestThreadedFacts:
    def test_concurrent_adds(self, tmp_path) -> None:
        store = FactStore(tmp_path / "facts.db")
        try:
            def worker(i: int) -> None:
                store.add_fact(f"Fact number {i}")

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert store.count() == 8
        finally:
            store.close()
