"""Tests for training triggers (auto-trigger threshold logic)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from nova_ai.learning.training.triggers import (
    count_new_pairs_since,
    maybe_auto_trigger,
    scheduled_task_metadata,
    should_auto_trigger,
)


def _trace_store(n_traces: int = 10) -> MagicMock:
    store = MagicMock()
    traces = []
    for i in range(n_traces):
        t = MagicMock()
        t.feedback = 0.9
        t.outcome = "success"
        t.query = f"q{i}"
        t.result = f"a{i}"
        t.started_at = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
        traces.append(t)
    store.list_traces.return_value = traces
    return store


class TestShouldAutoTrigger:
    def _configs(self, *, auto_trigger: bool = True, enabled: bool = True,
                 min_pairs: int = 5, auto_update: bool = True):
        training_cfg = MagicMock()
        training_cfg.enabled = enabled
        training_cfg.auto_trigger = auto_trigger
        training_cfg.min_pairs = min_pairs

        learning_cfg = MagicMock()
        learning_cfg.auto_update = auto_update
        return training_cfg, learning_cfg

    def test_all_conditions_met(self) -> None:
        training_cfg, learning_cfg = self._configs()
        ok, reason = should_auto_trigger(
            trace_store=_trace_store(20),
            run_store=MagicMock(is_running=lambda: False,
                                last_successful_run=lambda: None),
            config=training_cfg,
            learning_config=learning_cfg,
        )
        assert ok
        assert "20 new" in reason

    def test_auto_update_off_blocks(self) -> None:
        training_cfg, learning_cfg = self._configs(auto_update=False)
        ok, reason = should_auto_trigger(
            trace_store=_trace_store(20),
            run_store=MagicMock(),
            config=training_cfg,
            learning_config=learning_cfg,
        )
        assert not ok
        assert "auto_update" in reason

    def test_training_disabled_blocks(self) -> None:
        training_cfg, learning_cfg = self._configs(enabled=False)
        ok, _ = should_auto_trigger(
            trace_store=_trace_store(20),
            run_store=MagicMock(),
            config=training_cfg,
            learning_config=learning_cfg,
        )
        assert not ok

    def test_auto_trigger_off_blocks(self) -> None:
        training_cfg, learning_cfg = self._configs(auto_trigger=False)
        ok, reason = should_auto_trigger(
            trace_store=_trace_store(20),
            run_store=MagicMock(),
            config=training_cfg,
            learning_config=learning_cfg,
        )
        assert not ok
        assert "auto_trigger" in reason

    def test_run_in_flight_blocks(self) -> None:
        training_cfg, learning_cfg = self._configs()
        ok, reason = should_auto_trigger(
            trace_store=_trace_store(20),
            run_store=MagicMock(is_running=lambda: True,
                                last_successful_run=lambda: None),
            config=training_cfg,
            learning_config=learning_cfg,
        )
        assert not ok
        assert "in flight" in reason

    def test_too_few_new_pairs_blocks(self) -> None:
        training_cfg, learning_cfg = self._configs(min_pairs=50)
        with patch(
            "nova_ai.learning.training.triggers.count_new_pairs_since",
            return_value=3,
        ):
            ok, reason = should_auto_trigger(
                trace_store=_trace_store(3),
                run_store=MagicMock(is_running=lambda: False,
                                    last_successful_run=lambda: None),
                config=training_cfg,
                learning_config=learning_cfg,
            )
        assert not ok
        assert "3 new pairs" in reason


class TestCountNewPairs:
    def test_counts_all_without_since(self) -> None:
        with patch(
            "nova_ai.learning.training.data.TrainingDataMiner.extract_sft_pairs",
            return_value=[{"input": f"q{i}", "output": f"a{i}"} for i in range(7)],
        ):
            n = count_new_pairs_since(MagicMock())
        assert n == 7

    def test_counts_only_after_cutoff(self) -> None:
        store = _trace_store(10)
        pairs = [{"input": f"q{i}", "output": f"a{i}"} for i in range(10)]

        with patch(
            "nova_ai.learning.training.data.TrainingDataMiner.extract_sft_pairs",
            return_value=pairs,
        ):
            n = count_new_pairs_since(
                store, since_iso="2020-01-01T00:00:00+00:00"
            )
        assert n == 10  # all traces after 2020

        with patch(
            "nova_ai.learning.training.data.TrainingDataMiner.extract_sft_pairs",
            return_value=pairs,
        ):
            n = count_new_pairs_since(
                store, since_iso="2030-01-01T00:00:00+00:00"
            )
        assert n == 0  # all traces before 2030


class TestMaybeAutoTrigger:
    def test_returns_none_when_not_firing(self) -> None:
        training_cfg = MagicMock()
        training_cfg.enabled = False
        learning_cfg = MagicMock(auto_update=True)

        result = maybe_auto_trigger(
            trace_store=MagicMock(),
            run_store=MagicMock(),
            config=training_cfg,
            learning_config=learning_cfg,
        )
        assert result is None


class TestSchedulerMetadata:
    def test_metadata_marker(self) -> None:
        assert scheduled_task_metadata() == {"kind": "train"}
