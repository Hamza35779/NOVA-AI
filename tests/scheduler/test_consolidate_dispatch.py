"""Tests for the scheduler ``kind == "consolidate"`` task dispatch."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nova_ai.core.config import ConsolidationConfig, LearningConfig
from nova_ai.scheduler.scheduler import ScheduledTask, TaskScheduler
from nova_ai.scheduler.store import SchedulerStore


@pytest.fixture()
def store(tmp_path):
    s = SchedulerStore(tmp_path / "scheduler_test.db")
    yield s
    s.close()


@pytest.fixture()
def scheduler(store):
    sched = TaskScheduler(store, poll_interval=1)
    yield sched
    sched.stop()


def _task() -> ScheduledTask:
    return ScheduledTask(
        id="consolidate-task",
        prompt="",
        schedule_type="cron",
        schedule_value="0 3 * * *",
        metadata={"kind": "consolidate"},
    )


def _learning_cfg(enabled: bool = True):
    return LearningConfig(
        consolidation=ConsolidationConfig(enabled=enabled)
    )


class TestConsolidationDispatch:
    def test_disabled_config_skips(
        self, scheduler: TaskScheduler
    ) -> None:
        scheduler.set_training_hooks(
            learning_config=_learning_cfg(enabled=False),
            trace_store=MagicMock(),
        )
        result = scheduler._run_consolidation_task(_task())
        assert result == (
            "[consolidate] learning.consolidation.enabled is false; skipping"
        )

    def test_completed_run_formatted(
        self, scheduler: TaskScheduler, monkeypatch, tmp_path
    ) -> None:
        scheduler.set_training_hooks(
            learning_config=_learning_cfg(),
            trace_store=MagicMock(),
        )
        captured: dict = {}

        def fake_run(**kwargs):
            captured.update(kwargs)
            return {
                "status": "completed",
                "run_id": "consol_abc123",
                "clusters": 2,
                "facts_added": 5,
                "facts_superseded": 1,
                "decayed": 3,
            }

        monkeypatch.setattr(
            "nova_ai.memory.consolidation.pipeline.run_consolidation", fake_run
        )
        result = scheduler._run_consolidation_task(_task())
        assert "consol_abc123" in result
        assert "completed" in result
        assert "facts_added=5" in result
        assert "superseded=1" in result
        assert "decayed=3" in result
        # Provenance: scheduled trigger, stores wired to the config dir.
        assert captured["trigger"] == "scheduled"
        assert captured["run_store"] is not None
        assert captured["fact_store"] is not None

    def test_skip_reason_passthrough(
        self, scheduler: TaskScheduler, monkeypatch
    ) -> None:
        scheduler.set_training_hooks(
            learning_config=_learning_cfg(),
            trace_store=MagicMock(),
        )
        monkeypatch.setattr(
            "nova_ai.memory.consolidation.pipeline.run_consolidation",
            lambda **kwargs: {
                "status": "skipped", "reason": "no clusters large enough",
            },
        )
        result = scheduler._run_consolidation_task(_task())
        assert result == "[consolidate] skipped: no clusters large enough"

    def test_no_learning_config_skips(
        self, scheduler: TaskScheduler, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            TaskScheduler, "_training_learning_config", lambda self: None
        )
        result = scheduler._run_consolidation_task(_task())
        assert "enabled is false" in result

    def test_execute_task_routes_consolidate_kind(
        self, store: SchedulerStore, tmp_path, monkeypatch
    ) -> None:
        """Full _execute_task path: kind=consolidate dispatch succeeds."""
        import nova_ai.core.config as config_mod
        import nova_ai.scheduler.scheduler as sched_mod

        monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_DIR", tmp_path)
        monkeypatch.setattr(
            sched_mod.TaskScheduler,
            "_training_learning_config",
            lambda self: _learning_cfg(enabled=False),
        )
        sched = TaskScheduler(
            store, system=MagicMock(), poll_interval=1
        )  # non-None system enables the kind dispatch path
        task = sched.create_task(
            "sleep cycle",
            "once",
            "2030-01-01T00:00:00+00:00",
            metadata={"kind": "consolidate"},
        )
        sched._execute_task(ScheduledTask.from_dict(store.get_task(task.id)))
        logs = store.get_run_logs(task.id)
        assert len(logs) == 1
        assert logs[0]["success"] == 1
        assert "enabled is false" in logs[0]["result"]
