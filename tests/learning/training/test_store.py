"""Tests for TrainingRunStore and the training pipeline (torch-free)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nova_ai.core.config import TrainingConfig
from nova_ai.learning.training.pipeline import (
    active_adapter_path,
    promote_adapter,
    run_training,
)
from nova_ai.learning.training.store import TrainingRunStore


@pytest.fixture()
def run_store(tmp_path: Path) -> TrainingRunStore:
    return TrainingRunStore(tmp_path / "runs.db")


def _pairs(n: int) -> list[dict]:
    return [
        {"input": f"q{i}", "output": f"a{i}", "query_class": "math",
         "model": "qwen3:8b", "feedback": 0.9}
        for i in range(n)
    ]


class TestTrainingRunStore:
    def test_start_and_finish_run(self, run_store: TrainingRunStore) -> None:
        run_store.start_run("r1", trigger="manual", base_model="qwen3:8b")
        record = run_store.get_run("r1")
        assert record is not None
        assert record["status"] == "running"
        assert record["base_model"] == "qwen3:8b"

        run_store.finish_run(
            "r1",
            status="completed",
            pairs=120,
            avg_loss=0.31,
            adapter_path="/adapters/r1",
            deploy_results=[{"target": "adapter", "ok": True, "detail": "/x"}],
            benchmark_before=0.70,
            benchmark_after=0.74,
            benchmark_delta=0.04,
        )
        record = run_store.get_run("r1")
        assert record["status"] == "completed"
        assert record["pairs"] == 120
        assert record["avg_loss"] == pytest.approx(0.31)
        assert record["deploy_results"][0]["target"] == "adapter"
        assert record["benchmark_delta"] == pytest.approx(0.04)
        assert record["ended_at"] is not None

    def test_latest_and_list(self, run_store: TrainingRunStore) -> None:
        run_store.start_run("r1")
        run_store.start_run("r2")
        assert run_store.latest_run()["id"] == "r2"
        assert len(run_store.list_runs()) == 2

    def test_last_successful_run(self, run_store: TrainingRunStore) -> None:
        run_store.start_run("r1")
        run_store.finish_run("r1", status="failed", error="boom")
        assert run_store.last_successful_run() is None

        run_store.start_run("r2")
        run_store.finish_run("r2", status="completed")
        assert run_store.last_successful_run()["id"] == "r2"

    def test_is_running(self, run_store: TrainingRunStore) -> None:
        assert not run_store.is_running()
        run_store.start_run("r1")
        assert run_store.is_running()
        run_store.finish_run("r1", status="failed", error="x")
        assert not run_store.is_running()

    def test_get_missing_returns_none(self, run_store: TrainingRunStore) -> None:
        assert run_store.get_run("nope") is None
        assert run_store.latest_run() is None


def _pipeline_mocks(pairs: int = 100):
    """Patch the miner and SFT trainer for torch-free pipeline tests."""
    miner_patch = patch(
        "nova_ai.learning.training.data.TrainingDataMiner.extract_sft_pairs",
        return_value=_pairs(pairs),
    )
    return miner_patch


class TestRunTraining:
    def test_too_few_pairs_fails(self, tmp_path: Path, run_store) -> None:
        with _pipeline_mocks(pairs=3):
            record = run_training(
                trace_store=MagicMock(),
                config=TrainingConfig(min_pairs=50),
                run_store=run_store,
                training_root=tmp_path / "training",
            )
        assert record["status"] == "failed"
        assert "3 qualifying pairs" in record["error"]

    def test_torch_missing_fails(self, tmp_path: Path, run_store) -> None:
        with _pipeline_mocks():
            with patch("nova_ai.learning.training.lora.HAS_TORCH", False):
                record = run_training(
                    trace_store=MagicMock(),
                    config=TrainingConfig(min_pairs=10),
                    run_store=run_store,
                    training_root=tmp_path / "training",
                )
        assert record["status"] == "failed"
        assert "torch" in record["error"]

    def test_successful_run_writes_meta(self, tmp_path: Path, run_store) -> None:
        training_root = tmp_path / "training"

        fake_trainer = MagicMock()
        fake_trainer.train_on_pairs.return_value = {
            "status": "completed",
            "avg_loss": 0.25,
            "adapter_path": str(training_root / "adapters" / "x" / "final"),
        }
        trainer_patch = patch(
            "nova_ai.learning.intelligence.sft_trainer.SFTTrainer",
            return_value=fake_trainer,
        )

        with _pipeline_mocks(), trainer_patch, patch(
            "nova_ai.learning.training.lora.HAS_TORCH", True
        ):
            record = run_training(
                trace_store=MagicMock(),
                config=TrainingConfig(min_pairs=10, deploy_targets=[]),
                run_store=run_store,
                training_root=training_root,
            )

        assert record["status"] == "pending_review"  # auto_apply off
        assert record["pairs"] == 100
        assert record["avg_loss"] == pytest.approx(0.25)
        assert record["adapter_path"] is not None

    def test_benchmark_gate_rolls_back(self, tmp_path: Path, run_store) -> None:
        training_root = tmp_path / "training"

        fake_trainer = MagicMock()
        fake_trainer.train_on_pairs.return_value = {
            "status": "completed", "avg_loss": 0.25,
            "adapter_path": str(training_root / "adapters" / "x"),
        }
        trainer_patch = patch(
            "nova_ai.learning.intelligence.sft_trainer.SFTTrainer",
            return_value=fake_trainer,
        )
        runner = MagicMock(side_effect=[0.70, 0.701])  # pre, post — tiny delta

        with _pipeline_mocks(), trainer_patch, patch(
            "nova_ai.learning.training.lora.HAS_TORCH", True
        ):
            record = run_training(
                trace_store=MagicMock(),
                config=TrainingConfig(min_pairs=10, deploy_targets=[]),
                run_store=run_store,
                training_root=training_root,
                benchmark_runner=runner,
                min_improvement=0.02,
            )

        assert record["status"] == "rolled_back"
        assert record["benchmark_delta"] == pytest.approx(0.001)

    def test_gate_pass_auto_apply_deploys(self, tmp_path: Path, run_store) -> None:
        training_root = tmp_path / "training"

        fake_trainer = MagicMock()
        fake_trainer.train_on_pairs.return_value = {
            "status": "completed", "avg_loss": 0.25,
            "adapter_path": str(training_root / "adapters" / "x"),
        }
        trainer_patch = patch(
            "nova_ai.learning.intelligence.sft_trainer.SFTTrainer",
            return_value=fake_trainer,
        )
        runner = MagicMock(side_effect=[0.70, 0.80])  # delta +0.10
        deploy_patch = patch(
            "nova_ai.learning.training.pipeline.deploy",
            return_value=MagicMock(
                ok=True,
                to_list=lambda: [{"target": "adapter", "ok": True, "detail": "/x"}],
            ),
        )

        with _pipeline_mocks(), trainer_patch, deploy_patch, patch(
            "nova_ai.learning.training.lora.HAS_TORCH", True
        ):
            record = run_training(
                trace_store=MagicMock(),
                config=TrainingConfig(
                    min_pairs=10,
                    auto_apply=True,
                    deploy_targets=["adapter"],
                ),
                run_store=run_store,
                training_root=training_root,
                benchmark_runner=runner,
                min_improvement=0.02,
            )

        assert record["status"] == "completed"
        assert record["deploy_results"][0]["ok"] is True
        assert record["benchmark_delta"] == pytest.approx(0.10)

    def test_pending_review_does_not_deploy(self, tmp_path: Path, run_store) -> None:
        training_root = tmp_path / "training"

        fake_trainer = MagicMock()
        fake_trainer.train_on_pairs.return_value = {
            "status": "completed", "avg_loss": 0.25,
            "adapter_path": str(training_root / "adapters" / "x"),
        }
        trainer_patch = patch(
            "nova_ai.learning.intelligence.sft_trainer.SFTTrainer",
            return_value=fake_trainer,
        )
        deploy_patch = patch(
            "nova_ai.learning.training.pipeline.deploy"
        )

        with _pipeline_mocks(), trainer_patch, deploy_patch as mock_deploy, patch(
            "nova_ai.learning.training.lora.HAS_TORCH", True
        ):
            record = run_training(
                trace_store=MagicMock(),
                config=TrainingConfig(min_pairs=10, auto_apply=False),
                run_store=run_store,
                training_root=training_root,
            )

        assert record["status"] == "pending_review"
        mock_deploy.assert_not_called()
        assert record["deploy_results"] == []


class TestAdapterPointer:
    def test_promote_and_active(self, tmp_path: Path) -> None:
        training_root = tmp_path / "training"
        adapter = tmp_path / "adapters" / "a1"
        adapter.mkdir(parents=True)

        assert active_adapter_path(training_root) is None

        promote_adapter(
            adapter,
            training_root=training_root,
            base_model="qwen3:8b",
            run_id="r1",
        )
        active = active_adapter_path(training_root)
        assert active == adapter.resolve()

    def test_active_missing_dir_returns_none(self, tmp_path: Path) -> None:
        training_root = tmp_path / "training"
        adapter = tmp_path / "adapters" / "ghost"
        adapter.mkdir(parents=True)
        promote_adapter(
            adapter, training_root=training_root, base_model="m", run_id="r"
        )
        # Delete the dir after promotion — pointer now dangles.
        import shutil

        shutil.rmtree(adapter)
        assert active_adapter_path(training_root) is None
