"""Tests for extract_preference_pairs — fork/regen/thumbs mining."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from nova_ai.conversations.store import ConversationStore
from nova_ai.core.types import Trace
from nova_ai.learning.training.data import extract_preference_pairs
from nova_ai.traces.store import TraceStore


@pytest.fixture()
def conv_store(tmp_path):
    s = ConversationStore(tmp_path / "conv.db")
    yield s
    s.close()


@pytest.fixture()
def trace_store(tmp_path):
    s = TraceStore(tmp_path / "traces.db")
    yield s
    s.close()


def _trace(query, result, feedback, started=None):
    t = Trace(query=query, agent="simple", model="m", result=result, feedback=feedback)
    if started:
        t.started_at = started
    return t


class TestRecordedPairs:
    def test_fork_pair_extracted(self, conv_store):
        conv = conv_store.create_conversation("t")
        root = conv_store._conn.execute(
            "SELECT id FROM conv_nodes WHERE conversation_id=?",
            (conv["id"],),
        ).fetchone()[0]
        user = conv_store.add_message(conv["id"], root, "user", "what is X?")
        a1 = conv_store.add_message(conv["id"], user, "assistant", "good answer")
        a2 = conv_store.add_message(conv["id"], user, "assistant", "bad answer")
        conv_store.add_sibling_choice(
            conv["id"],
            [{"role": "user", "content": "what is X?"}],
            a1,
            [a2],
            source="fork",
        )
        pairs = extract_preference_pairs(conv_store)
        assert len(pairs) == 1
        assert pairs[0]["prompt"] == "what is X?"
        assert pairs[0]["chosen"] == "good answer"
        assert pairs[0]["rejected"] == "bad answer"
        assert pairs[0]["source"] == "fork"

    def test_multiple_rejected_yields_multiple_pairs(self, conv_store):
        conv = conv_store.create_conversation("t")
        root = conv_store._conn.execute(
            "SELECT id FROM conv_nodes WHERE conversation_id=?",
            (conv["id"],),
        ).fetchone()[0]
        user = conv_store.add_message(conv["id"], root, "user", "q")
        a1 = conv_store.add_message(conv["id"], user, "assistant", "winner")
        a2 = conv_store.add_message(conv["id"], user, "assistant", "loser1")
        a3 = conv_store.add_message(conv["id"], user, "assistant", "loser2")
        conv_store.add_sibling_choice(conv["id"], [], a1, [a2, a3])
        pairs = extract_preference_pairs(conv_store)
        assert len(pairs) == 2
        assert {p["rejected"] for p in pairs} == {"loser1", "loser2"}

    def test_identical_chosen_rejected_dropped(self, conv_store):
        conv = conv_store.create_conversation("t")
        root = conv_store._conn.execute(
            "SELECT id FROM conv_nodes WHERE conversation_id=?",
            (conv["id"],),
        ).fetchone()[0]
        user = conv_store.add_message(conv["id"], root, "user", "q")
        a1 = conv_store.add_message(conv["id"], user, "assistant", "same")
        a2 = conv_store.add_message(conv["id"], user, "assistant", "same")
        conv_store.add_sibling_choice(conv["id"], [], a1, [a2])
        assert extract_preference_pairs(conv_store) == []


class TestTracePairs:
    def test_regen_signal_improving_feedback(self, trace_store):
        early = datetime(2026, 1, 1, tzinfo=timezone.utc)
        late = datetime(2026, 1, 2, tzinfo=timezone.utc)
        trace_store.save(_trace("q", "first attempt", 0.3, started=early))
        trace_store.save(_trace("q", "better attempt", 0.9, started=late))
        pairs = extract_preference_pairs(None, trace_store=trace_store)
        assert len(pairs) == 1
        assert pairs[0]["chosen"] == "better attempt"
        assert pairs[0]["rejected"] == "first attempt"
        assert pairs[0]["source"] == "regen"

    def test_no_improvement_no_pair(self, trace_store):
        early = datetime(2026, 1, 1, tzinfo=timezone.utc)
        late = datetime(2026, 1, 2, tzinfo=timezone.utc)
        trace_store.save(_trace("q", "same result", 0.9, started=early))
        trace_store.save(_trace("q", "same result", 0.5, started=late))
        assert extract_preference_pairs(None, trace_store=trace_store) == []

    def test_thumbs_signal_low_then_high(self, trace_store):
        early = datetime(2026, 1, 1, tzinfo=timezone.utc)
        late = datetime(2026, 1, 2, tzinfo=timezone.utc)
        trace_store.save(_trace("q", "bad", 0.1, started=early))
        trace_store.save(_trace("q", "great", 0.8, started=late))
        pairs = extract_preference_pairs(None, trace_store=trace_store, min_quality=0.7)
        assert pairs[0]["source"] == "regen"  # improved past min_quality

    def test_different_queries_not_paired(self, trace_store):
        trace_store.save(_trace("q1", "r1", 0.1))
        trace_store.save(_trace("q2", "r2", 0.9))
        assert extract_preference_pairs(None, trace_store=trace_store) == []


class TestCombined:
    def test_both_sources_merge(self, conv_store, trace_store):
        conv = conv_store.create_conversation("t")
        root = conv_store._conn.execute(
            "SELECT id FROM conv_nodes WHERE conversation_id=?",
            (conv["id"],),
        ).fetchone()[0]
        user = conv_store.add_message(conv["id"], root, "user", "fork question")
        a1 = conv_store.add_message(conv["id"], user, "assistant", "chosen one")
        a2 = conv_store.add_message(conv["id"], user, "assistant", "rejected one")
        conv_store.add_sibling_choice(conv["id"], [], a1, [a2])

        early = datetime(2026, 1, 1, tzinfo=timezone.utc)
        late = datetime(2026, 1, 2, tzinfo=timezone.utc)
        trace_store.save(_trace("trace q", "worse", 0.2, started=early))
        trace_store.save(_trace("trace q", "better", 0.8, started=late))

        pairs = extract_preference_pairs(conv_store, trace_store=trace_store)
        assert len(pairs) == 2
        assert {p["source"] for p in pairs} == {"fork", "regen"}
