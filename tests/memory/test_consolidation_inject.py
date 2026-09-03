"""Tests for core-memory injection (inject.py) and the orchestrator hook."""

from __future__ import annotations

import pytest

from nova_ai.core.types import Message, Role
from nova_ai.memory.consolidation.inject import core_memory_block, inject


@pytest.fixture()
def fact_store(tmp_path):
    from nova_ai.memory.consolidation.store import FactStore

    s = FactStore(tmp_path / "facts.db")
    yield s
    s.close()


class TestCoreMemoryBlock:
    def test_empty_store_renders_empty(self, fact_store) -> None:
        assert core_memory_block(fact_store) == ""

    def test_renders_header_and_facts(self, fact_store) -> None:
        fact_store.add_fact("The user prefers dark mode", confidence=0.9)
        fact_store.add_fact("Deploys on Fridays", confidence=0.8)
        block = core_memory_block(fact_store)
        assert block.startswith("## What NOVA knows about you")
        assert "- The user prefers dark mode" in block
        assert "- Deploys on Fridays" in block

    def test_excludes_non_active_facts(self, fact_store) -> None:
        fid = fact_store.add_fact("Gone fact", confidence=0.99)
        fact_store.set_status(fid, "decayed")
        assert core_memory_block(fact_store) == ""

    def test_broken_store_returns_empty(self) -> None:
        class Broken:
            def export_core(self, max_chars):
                raise RuntimeError("db locked")

        assert core_memory_block(Broken()) == ""


class TestInject:
    def test_prepends_system_message(self, fact_store) -> None:
        fact_store.add_fact("The user prefers dark mode", confidence=0.9)
        messages = [Message(role=Role.USER, content="hi")]
        out = inject(messages, fact_store)
        assert len(out) == 2
        assert out[0].role == Role.SYSTEM
        assert "What NOVA knows about you" in out[0].content
        assert out[1] is messages[0]

    def test_empty_facts_returns_original(self, fact_store) -> None:
        messages = [Message(role=Role.USER, content="hi")]
        out = inject(messages, fact_store)
        assert out == messages
        assert out is messages or len(out) == 1

    def test_none_store_returns_original(self) -> None:
        messages = [Message(role=Role.USER, content="hi")]
        assert inject(messages, None) is messages

    def test_input_not_mutated(self, fact_store) -> None:
        fact_store.add_fact("Some fact", confidence=0.9)
        messages = [Message(role=Role.USER, content="hi")]
        inject(messages, fact_store)
        assert len(messages) == 1

    def test_failing_block_falls_back(self, fact_store) -> None:
        fact_store.add_fact("Some fact", confidence=0.9)

        class Exploding:
            def export_core(self, max_chars):
                raise RuntimeError("boom")

        messages = [Message(role=Role.USER, content="hi")]
        assert inject(messages, Exploding()) is messages
