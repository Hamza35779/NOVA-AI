"""Tests for the scheduler DPO lane dispatch (kind=train, lane=dpo)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nova_ai.core.config import LearningConfig, TrainingConfig
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


def _task(lane: str = "dpo") -> ScheduledTask:
    return ScheduledTask(
        id="train-dpo-task",
        prompt="",
        schedule_type="cron",
        schedule_value="0 4 * * *",
        metadata={"kind": "train", "lane": lane},
    )


def _learning_cfg(dpo_enabled: bool = True) -> LearningConfig:
    return LearningConfig(
        training=TrainingConfig(enabled=True, dpo_enabled=dpo_enabled, min_pairs=1),
    )


class TestTrainDPODispatch:
    def test_dpo_lane_blocked_when_disabled(self, scheduler: TaskScheduler) -> None:
        scheduler.set_training_hooks(
            learning_config=_learning_cfg(dpo_enabled=False),
            trace_store=MagicMock(),
        )
        result = scheduler._run_training_task(_task("dpo"))
        assert result == (
            "[train] lane=dpo but learning.training.dpo_enabled is false; skipping"
        )

    def test_sft_lane_no_lane_key(self, scheduler: TaskScheduler) -> None:
        """A plain train task (no lane key) still routes as sft."""
        task = ScheduledTask(
            id="train-task",
            prompt="",
            schedule_type="cron",
            schedule_value="0 4 * * *",
            metadata={"kind": "train"},
        )
        scheduler.set_training_hooks(
            learning_config=_learning_cfg(dpo_enabled=False),
            trace_store=MagicMock(),
        )
        with patch(
            "nova_ai.learning.training.triggers.run_scheduled_training",
            return_value={"id": "r1", "status": "pending_review", "pairs": 3},
        ) as run_mock:
            result = scheduler._run_training_task(task)
        assert "pending_review" in result
        kwargs = run_mock.call_args.kwargs
        assert kwargs["lane"] == "sft"

    def test_dpo_lane_passes_lane_through(self, scheduler: TaskScheduler) -> None:
        scheduler.set_training_hooks(
            learning_config=_learning_cfg(dpo_enabled=True),
            trace_store=MagicMock(),
        )
        with patch(
            "nova_ai.learning.training.triggers.run_scheduled_training",
            return_value={
                "id": "r2",
                "status": "pending_review",
                "pairs": 8,
                "lane": "dpo",
            },
        ) as run_mock:
            result = scheduler._run_training_task(_task("dpo"))
        assert run_mock.call_args.kwargs["lane"] == "dpo"
        assert "lane=dpo" in result
        assert "pairs=8" in result
