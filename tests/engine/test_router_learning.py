"""Tests for the Router Learning feedback store."""

from __future__ import annotations

from pathlib import Path

from nova_ai.engine.router_learning import RoutingFeedbackStore, _query_hash


class TestQueryHash:
    def test_same_content_same_hash(self):
        assert _query_hash("hello world") == _query_hash("hello world")

    def test_different_content_different_hash(self):
        assert _query_hash("hello") != _query_hash("goodbye")

    def test_whitespace_normalized(self):
        assert _query_hash("hello   world") == _query_hash("hello world")

    def test_case_normalized(self):
        assert _query_hash("Hello World") == _query_hash("hello world")


class TestRoutingFeedbackStore:
    def _store(self, tmpdir):
        return RoutingFeedbackStore(db_path=Path(tmpdir) / "test.db")

    def test_record_decision(self, tmp_path):
        store = self._store(tmp_path)
        store.record_decision("msg1", "What is the capital of France?", "small")
        stats = store.get_stats()
        assert stats["total_decisions"] == 1

    def test_record_feedback_and_correction(self, tmp_path):
        store = self._store(tmp_path)
        content = "Analyze the economic impact of climate change in detail"
        for i in range(3):
            store.record_feedback(f"msg{i}", content, "small", "large")
        correction = store.get_correction(content, "small")
        assert correction == "large"

    def test_correction_below_threshold_returns_none(self, tmp_path):
        store = self._store(tmp_path)
        content = "Analyze the economic impact of climate change in detail"
        for i in range(2):  # Only 2, threshold is 3
            store.record_feedback(f"msg{i}", content, "small", "large")
        correction = store.get_correction(content, "small")
        assert correction is None

    def test_thumbs_up_records_no_correction(self, tmp_path):
        store = self._store(tmp_path)
        store.record_implicit_feedback("msg1", "hi there", "small", thumbs_up=True)
        stats = store.get_stats()
        assert stats["total_feedback"] == 0

    def test_thumbs_down_upgrades_tier(self, tmp_path):
        store = self._store(tmp_path)
        content = "Write a detailed analysis"
        for i in range(3):
            store.record_implicit_feedback(f"msg{i}", content, "small", thumbs_up=False)
        correction = store.get_correction(content, "small")
        assert correction == "medium"

    def test_same_tier_feedback_ignored(self, tmp_path):
        store = self._store(tmp_path)
        store.record_feedback("msg1", "some query", "medium", "medium")
        stats = store.get_stats()
        assert stats["total_feedback"] == 0
