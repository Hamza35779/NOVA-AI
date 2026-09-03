"""Tests for SessionMiner (clustering) and the consolidation pipeline."""

from __future__ import annotations

import pytest

from nova_ai.core.types import Trace
from nova_ai.memory.consolidation.cluster import SessionMiner
from nova_ai.memory.consolidation.pipeline import run_consolidation
from nova_ai.memory.consolidation.store import FactStore
from nova_ai.traces.store import TraceStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _trace(query: str, result: str = "", feedback: float = 0.9) -> Trace:
    return Trace(query=query, agent="simple", result=result, feedback=feedback)


@pytest.fixture()
def seeded_store(tmp_path):
    store = TraceStore(tmp_path / "traces.db")
    queries = [
        # code cluster (4 traces) — queries carry code regex keywords so
        # classify_query() buckets them as "code"
        "write a python script using `import os` to rename files in bulk",
        "write a python script using `import csv` to parse csv rows",
        "write a python script using `import shutil` to backup my folders",
        "write a python script using `import PIL` to resize images",
        # math cluster (4 traces)
        "solve the equation 3x + 7 = 22 step by step",
        "solve the equation 5y - 3 = 18 step by step",
        "solve the equation 2z * 4 = 40 step by step",
        "solve the equation 9a / 3 = 12 step by step",
        # general singletons (below cluster threshold)
        "hello",
        "thanks",
    ]
    for q in queries:
        store.save(_trace(q, result=f"answer to: {q}"))
    yield store
    store.close()


class FakeEmbedder:
    """Deterministic embedder: bag-of-words hashing to a fixed dim."""

    DIM = 32

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vec = [0.0] * self.DIM
            for word in text.lower().split():
                vec[hash(word) % self.DIM] += 1.0
            vectors.append(vec)
        return vectors


class FakeLLM:
    """Extraction LLM returning canned JSON per prompt."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


GOOD_RESPONSE = (
    '[{"content": "The user frequently asks for python file automation",'
    ' "topic": "automation", "confidence": 0.8}]'
)


@pytest.fixture()
def fact_store(tmp_path):
    s = FactStore(tmp_path / "consolidation" / "facts.db")
    yield s
    s.close()


def _cfg(**overrides):
    from nova_ai.core.config import ConsolidationConfig

    defaults = {"enabled": True, "min_session_messages": 4}
    defaults.update(overrides)
    return ConsolidationConfig(**defaults)


# ---------------------------------------------------------------------------
# SessionMiner
# ---------------------------------------------------------------------------


class TestSessionMiner:
    def test_class_only_fallback_groups_by_class(
        self, seeded_store
    ) -> None:
        miner = SessionMiner(seeded_store, embedder=None)
        clusters = miner.mine(min_cluster_size=4)
        hints = {c["topic_hint"] for c in clusters}
        assert hints == {"code", "math"}

    def test_embedded_clustering_splits_within_class(
        self, seeded_store
    ) -> None:
        class SplittingEmbedder(FakeEmbedder):
            """Cosine-1.0 within each group, ~0.0 across groups."""

            GROUPS = {
                "write a python script": 1,
                "solve the equation": 2,
                "hello": 3,
                "thanks": 3,
            }

            def embed(self, texts: list[str]) -> list[list[float]]:
                # Reuse the hashing embedder, but give each group a large
                # shared block so same-group vectors land at angle ~0.
                base = super().embed(texts)
                out = []
                for text, vec in zip(texts, base):
                    tag = next(
                        (g for prefix, g in self.GROUPS.items()
                         if text.startswith(prefix)),
                        0,
                    )
                    vec = list(vec)
                    vec[tag * 4 % self.DIM] += 5.0
                    vec[(tag * 4 + 1) % self.DIM] += 5.0
                    out.append(vec)
                return out

        miner = SessionMiner(
            seeded_store, embedder=SplittingEmbedder(), similarity_threshold=0.9
        )
        clusters = miner.mine(min_cluster_size=3)
        hints = {c["topic_hint"] for c in clusters}
        assert "code" in hints
        assert "math" in hints

    def test_small_clusters_dropped(self, seeded_store) -> None:
        miner = SessionMiner(seeded_store, embedder=None)
        clusters = miner.mine(min_cluster_size=100)
        assert clusters == []

    def test_empty_store(self, tmp_path) -> None:
        store = TraceStore(tmp_path / "empty.db")
        try:
            miner = SessionMiner(store, embedder=None)
            assert miner.mine(min_cluster_size=1) == []
        finally:
            store.close()

    def test_trace_ids_preserved(self, seeded_store) -> None:
        miner = SessionMiner(seeded_store, embedder=None)
        clusters = miner.mine(min_cluster_size=4)
        code = next(c for c in clusters if c["topic_hint"] == "code")
        assert len(code["trace_ids"]) == 4
        assert all(tid for tid in code["trace_ids"])

    def test_embedder_failure_falls_back(self, seeded_store) -> None:
        class ExplodingEmbedder:
            def embed(self, texts):
                raise RuntimeError("model gone")

        miner = SessionMiner(seeded_store, embedder=ExplodingEmbedder())
        clusters = miner.mine(min_cluster_size=4)
        assert {c["topic_hint"] for c in clusters} == {"code", "math"}

    def test_messages_include_roles_and_feedback(self, seeded_store) -> None:
        miner = SessionMiner(seeded_store, embedder=None)
        clusters = miner.mine(min_cluster_size=4)
        code = next(c for c in clusters if c["topic_hint"] == "code")
        roles = {m["role"] for m in code["messages"]}
        assert roles == {"user", "assistant"}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class TestPipelineGuards:
    def test_disabled_config_fails(
        self, seeded_store, fact_store, tmp_path
    ) -> None:
        result = run_consolidation(
            trace_store=seeded_store,
            fact_store=fact_store,
            config=_cfg(enabled=False),
            llm=FakeLLM(GOOD_RESPONSE),
        )
        assert result["status"] == "failed"
        assert "enabled is false" in result["error"]
        assert fact_store.count() == 0

    def test_in_flight_run_fails(self, seeded_store, fact_store, tmp_path) -> None:
        from nova_ai.memory.consolidation.store import ConsolidationRunStore

        run_store = ConsolidationRunStore(tmp_path / "runs.db")
        try:
            run_store.start_run("consol_inflight")
            result = run_consolidation(
                trace_store=seeded_store,
                fact_store=fact_store,
                config=_cfg(),
                run_store=run_store,
                llm=FakeLLM(GOOD_RESPONSE),
            )
            assert result["status"] == "failed"
            assert "already in flight" in result["error"]
        finally:
            run_store.close()

    def test_no_clusters_skips(self, tmp_path, fact_store) -> None:
        store = TraceStore(tmp_path / "empty.db")
        try:
            result = run_consolidation(
                trace_store=store,
                fact_store=fact_store,
                config=_cfg(),
                llm=FakeLLM(GOOD_RESPONSE),
            )
            assert result["status"] == "skipped"
        finally:
            store.close()


class TestPipelineHappyPath:
    def test_facts_added(
        self, seeded_store, fact_store
    ) -> None:
        llm = FakeLLM(GOOD_RESPONSE)
        result = run_consolidation(
            trace_store=seeded_store,
            fact_store=fact_store,
            config=_cfg(),
            llm=llm,
        )
        assert result["status"] == "completed"
        assert result["facts_added"] >= 1
        facts = fact_store.list_facts()
        assert any("python file automation" in f["content"] for f in facts)

    def test_llm_receives_cluster_context(
        self, seeded_store, fact_store
    ) -> None:
        llm = FakeLLM(GOOD_RESPONSE)
        run_consolidation(
            trace_store=seeded_store,
            fact_store=fact_store,
            config=_cfg(),
            llm=llm,
        )
        assert llm.prompts
        assert "python" in llm.prompts[0].lower()

    def test_run_record_persisted(
        self, seeded_store, fact_store, tmp_path
    ) -> None:
        from nova_ai.memory.consolidation.store import ConsolidationRunStore

        run_store = ConsolidationRunStore(tmp_path / "runs.db")
        try:
            result = run_consolidation(
                trace_store=seeded_store,
                fact_store=fact_store,
                config=_cfg(),
                run_store=run_store,
                llm=FakeLLM(GOOD_RESPONSE),
            )
            record = run_store.get_run(result["run_id"])
            assert record is not None
            assert record["status"] == "completed"
            assert record["summary"]["facts_added"] >= 1
        finally:
            run_store.close()

    def test_max_facts_cap(
        self, seeded_store, fact_store
    ) -> None:
        items = [
            '{"content": "Fact %d unique statement", "topic": "t",'
            ' "confidence": 0.6}' % i
            for i in range(10)
        ]
        many = "[" + ",".join(items) + "]"
        result = run_consolidation(
            trace_store=seeded_store,
            fact_store=fact_store,
            config=_cfg(max_facts_per_run=3),
            llm=FakeLLM(many),
        )
        assert result["facts_added"] == 3

    def test_unparseable_llm_output_adds_nothing(
        self, seeded_store, fact_store
    ) -> None:
        result = run_consolidation(
            trace_store=seeded_store,
            fact_store=fact_store,
            config=_cfg(),
            llm=FakeLLM("I cannot comply, here is some prose."),
        )
        assert result["status"] == "completed"
        assert result["facts_added"] == 0

    def test_fenced_json_tolerated(
        self, seeded_store, fact_store
    ) -> None:
        fenced = "```json\n" + GOOD_RESPONSE + "\n```"
        result = run_consolidation(
            trace_store=seeded_store,
            fact_store=fact_store,
            config=_cfg(),
            llm=FakeLLM(fenced),
        )
        assert result["facts_added"] >= 1

    def test_llm_failure_isolated_per_cluster(
        self, seeded_store, fact_store
    ) -> None:
        class FlakyLLM:
            def __init__(self) -> None:
                self.calls = 0

            def generate(self, prompt: str) -> str:
                self.calls += 1
                raise RuntimeError("ollama down")

        llm = FlakyLLM()
        result = run_consolidation(
            trace_store=seeded_store,
            fact_store=fact_store,
            config=_cfg(),
            llm=llm,
        )
        assert result["status"] == "completed"
        assert llm.calls >= 1
        assert result["facts_added"] == 0


class TestDedupAndContradictions:
    def test_duplicate_touched_not_readded(
        self, seeded_store, fact_store
    ) -> None:
        run_consolidation(
            trace_store=seeded_store,
            fact_store=fact_store,
            config=_cfg(),
            llm=FakeLLM(GOOD_RESPONSE),
        )
        before = fact_store.count()
        result = run_consolidation(
            trace_store=seeded_store,
            fact_store=fact_store,
            config=_cfg(),
            llm=FakeLLM(GOOD_RESPONSE),
        )
        assert result["facts_added"] == 0
        assert fact_store.count() == before

    def test_contradiction_supersedes_when_confident(
        self, seeded_store, fact_store
    ) -> None:
        fact_store.add_fact(
            "The user prefers tabs for indentation",
            topic="style",
            confidence=0.6,
        )
        response = (
            '[{"content": "The user does not prefer tabs for indentation",'
            ' "topic": "style", "confidence": 0.9}]'
        )
        result = run_consolidation(
            trace_store=seeded_store,
            fact_store=fact_store,
            config=_cfg(),
            llm=FakeLLM(response),
        )
        assert result["facts_added"] == 1
        assert result["facts_superseded"] == 1
        statuses = {
            f["content"]: f["status"] for f in fact_store.list_facts(status=None)
        }
        assert statuses["The user prefers tabs for indentation"] == "superseded"
        new_fact = [
            f
            for f in fact_store.list_facts(status=None)
            if "does not prefer tabs" in f["content"]
        ][0]
        assert new_fact["status"] == "active"

    def test_unconfident_contradiction_keeps_both(
        self, seeded_store, fact_store
    ) -> None:
        fact_store.add_fact(
            "The user prefers tabs for indentation",
            topic="style",
            confidence=0.95,
        )
        response = (
            '[{"content": "The user does not prefer tabs for indentation",'
            ' "topic": "style", "confidence": 0.4}]'
        )
        result = run_consolidation(
            trace_store=seeded_store,
            fact_store=fact_store,
            config=_cfg(),
            llm=FakeLLM(response),
        )
        assert result["facts_added"] == 1
        assert result["facts_superseded"] == 0
        assert fact_store.count() == 2

    def test_decay_runs_each_cycle(self, seeded_store, fact_store) -> None:
        fact_store.add_fact("Ancient fact", now=0.0)
        result = run_consolidation(
            trace_store=seeded_store,
            fact_store=fact_store,
            config=_cfg(),
            llm=FakeLLM(GOOD_RESPONSE),
        )
        assert result["decayed"] == 1
