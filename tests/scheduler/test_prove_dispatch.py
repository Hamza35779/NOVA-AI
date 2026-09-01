"""Tests for the scheduler ``kind == "prove"`` task dispatch."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nova_ai.core.config import LearningConfig, ProvingConfig
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
        id="prove-task",
        prompt="",
        schedule_type="cron",
        schedule_value="0 3 * * *",
        metadata={"kind": "prove"},
    )


def _learning_cfg(enabled: bool = True, auto_trigger: bool = True):
    return LearningConfig(
        proving=ProvingConfig(enabled=enabled, auto_trigger=auto_trigger)
    )


class TestProvingDispatch:
    def test_disabled_config_skips(
        self, scheduler: TaskScheduler, caplog: pytest.LogCaptureFixture
    ) -> None:
        scheduler.set_training_hooks(
            learning_config=_learning_cfg(enabled=False),
            trace_store=MagicMock(),
        )
        result = scheduler._run_proving_task(_task())
        assert result == "[prove] learning.proving.enabled is false; skipping"

    def test_auto_prove_results_formatted(
        self, scheduler: TaskScheduler, monkeypatch
    ) -> None:
        scheduler.set_training_hooks(
            learning_config=_learning_cfg(),
            trace_store=MagicMock(),
        )
        monkeypatch.setattr(
            "nova_ai.learning.proving.watcher.maybe_auto_prove",
            lambda **kwargs: [
                {"candidate": "new-model", "status": "completed",
                 "run_id": "prove_x", "adopted": {"code": "new-model"}},
            ],
        )
        result = scheduler._run_proving_task(_task())
        assert "new-model" in result
        assert "prove_x" in result
        assert "adopted" in result

    def test_skip_reason_passthrough(
        self, scheduler: TaskScheduler, monkeypatch
    ) -> None:
        scheduler.set_training_hooks(
            learning_config=_learning_cfg(),
            trace_store=MagicMock(),
        )
        monkeypatch.setattr(
            "nova_ai.learning.proving.watcher.maybe_auto_prove",
            lambda **kwargs: [
                {"status": "skipped", "reason": "no new models"},
            ],
        )
        result = scheduler._run_proving_task(_task())
        assert result == "[prove] skipped: no new models"

    def test_hook_receives_proving_root(
        self, scheduler: TaskScheduler, monkeypatch, tmp_path
    ) -> None:
        scheduler.set_training_hooks(
            learning_config=_learning_cfg(),
            trace_store=MagicMock(),
        )
        captured: dict = {}

        def fake_prove(**kwargs):
            captured.update(kwargs)
            return []

        monkeypatch.setattr(
            "nova_ai.learning.proving.watcher.maybe_auto_prove", fake_prove
        )
        scheduler._run_proving_task(_task())
        assert captured["proving_root"].name == "proving"
        assert captured["proving_root"].parent.name == "learning"

    def test_execute_task_routes_prove_kind(
        self, store: SchedulerStore, tmp_path, monkeypatch
    ) -> None:
        """Full _execute_task path: kind=prove dispatch succeeds and logs.

        proving.enabled=false needs no discovery at all — the store/write
        path is the only real IO, aimed at tmp_path via DEFAULT_CONFIG_DIR.
        """
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
            "prove check",
            "once",
            "2030-01-01T00:00:00+00:00",
            metadata={"kind": "prove"},
        )
        sched._execute_task(ScheduledTask.from_dict(store.get_task(task.id)))
        logs = store.get_run_logs(task.id)
        assert len(logs) == 1
        assert logs[0]["success"] == 1
        assert "enabled is false" in logs[0]["result"]
