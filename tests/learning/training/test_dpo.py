"""Tests for the DPO lane: DPOTrainer guards, pipeline wiring, CLI, scheduler."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from nova_ai.core.config import TrainingConfig
from nova_ai.core.types import Trace
from nova_ai.learning.training.dpo import (
    HAS_TRL,
    DPOTrainer,
    DPOTrainingConfig,
    format_preference_pairs,
)
from nova_ai.learning.training.pipeline import run_training
from nova_ai.learning.training.store import TrainingRunStore

# ---------------------------------------------------------------------------
# DPOTrainingConfig
# ---------------------------------------------------------------------------


class TestDPOTrainingConfig:
    def test_defaults(self) -> None:
        cfg = DPOTrainingConfig()
        assert cfg.beta == 0.1
        assert cfg.num_epochs == 1
        assert cfg.learning_rate == 5e-6
        assert cfg.loss_type == "sigmoid"
        assert cfg.target_modules == ["q_proj", "v_proj"]
        assert cfg.batch_size == 2

    def test_beta_validation(self) -> None:
        with pytest.raises(ValueError, match="beta"):
            DPOTrainingConfig(beta=0)

    def test_epochs_validation(self) -> None:
        with pytest.raises(ValueError, match="num_epochs"):
            DPOTrainingConfig(num_epochs=0)


class TestFormatPairs:
    def test_drops_incomplete_and_identical(self) -> None:
        pairs = [
            {"prompt": "p", "chosen": "a", "rejected": "b"},
            {"prompt": "p", "chosen": "x", "rejected": "x"},
            {"prompt": "", "chosen": "a", "rejected": "b"},
            {"prompt": "p", "chosen": "", "rejected": "b"},
        ]
        out = format_preference_pairs(pairs)
        assert out == [{"prompt": "p", "chosen": "a", "rejected": "b"}]

    def test_all_invalid_returns_empty(self) -> None:
        assert format_preference_pairs([{"prompt": "p"}]) == []


class TestDPOTrainerGuard:
    def test_import_error_without_trl(self) -> None:
        """Without trl installed, constructing DPOTrainer raises ImportError."""
        if HAS_TRL:
            pytest.skip("trl is installed; cannot test missing-trl path")
        with pytest.raises(ImportError, match="trl"):
            DPOTrainer(DPOTrainingConfig())


@pytest.mark.skipif(not HAS_TRL, reason="trl not installed")
class TestDPOTrainerWithTRL:
    def test_train_empty_pairs_skipped(self, tmp_path: Path) -> None:
        cfg = DPOTrainingConfig(output_dir=str(tmp_path / "out"))
        trainer = DPOTrainer(cfg, model_name="Qwen/Qwen3-0.6B")
        result = trainer.train([])
        assert result["status"] == "skipped"


# ---------------------------------------------------------------------------
# Pipeline lane wiring
# ---------------------------------------------------------------------------


class _FakeConvStore:
    """Minimal stand-in exposing the ConversationStore read API."""

    def __init__(self, pairs: list[dict]) -> None:
        self._pairs = pairs

    def list_preference_pairs(self, *, conversation_id=None, limit=1000):
        return self._pairs

    def get_node(self, node_id):
        return {
            "id": node_id,
            "content": f"answer-{node_id}",
            "role": "assistant",
        }


@pytest.fixture()
def env(tmp_path):
    run_store = TrainingRunStore(tmp_path / "runs.db")
    yield run_store, tmp_path
    run_store.close()


def _train_cfg(**kw):
    base = dict(enabled=True, min_pairs=1, max_pairs=100, deploy_targets=[])
    base.update(kw)
    return TrainingConfig(**base)


class TestPipelineLane:
    def test_dpo_disabled_by_config_rejected_via_min_pairs(self, env) -> None:
        """lane=dpo with zero preference data fails with the dpo message."""
        run_store, tmp_path = env
        trace_store = mock.MagicMock()
        trace_store.list_traces.return_value = []
        record = run_training(
            trace_store=trace_store,
            config=_train_cfg(dpo_enabled=True, dpo_min_pairs=5),
            run_store=run_store,
            training_root=tmp_path / "root",
            lane="dpo",
        )
        assert record["status"] == "failed"
        assert "lane=dpo" in record["error"]

    def test_sft_lane_still_mines_sft_pairs(self, env) -> None:
        run_store, tmp_path = env
        trace = Trace(
            query="What is 2+2?",
            agent="simple",
            model="m",
            result="4",
            feedback=0.9,
            outcome="success",
        )
        trace_store = mock.MagicMock()
        trace_store.list_traces.return_value = [trace]
        with mock.patch(
            "nova_ai.learning.intelligence.sft_trainer.SFTTrainer"
        ) as trainer_cls, mock.patch(
            "nova_ai.learning.training.lora.HAS_TORCH", True
        ):
            trainer_cls.return_value.train_on_pairs.return_value = {
                "status": "skipped",
                "reason": "stop before training",
            }
            record = run_training(
                trace_store=trace_store,
                config=_train_cfg(),
                run_store=run_store,
                training_root=tmp_path / "root",
                lane="sft",
            )
        assert record["status"] == "failed"  # 'skipped' maps to failure
        assert "training skipped" in record["error"]

    def test_dpo_lane_uses_conv_store_pairs(self, env) -> None:
        """With enough recorded pairs, the run reaches the trainer (mocked)."""
        run_store, tmp_path = env
        conv_store = _FakeConvStore(
            [
                {
                    "id": f"pref{i}",
                    "conversation_id": "conv1",
                    "prompt_path": [{"role": "user", "content": f"q{i}"}],
                    "chosen_id": "a1",
                    "rejected_ids": ["a2"],
                    "source": "fork",
                    "created_at": "2026-01-01T00:00:00+00:00",
                }
                for i in range(3)
            ]
        )
        # get_node returns realistic content so chosen/rejected differ.
        node_map = {
            "a1": {"id": "a1", "role": "assistant", "content": "good answer"},
            "a2": {"id": "a2", "role": "assistant", "content": "bad answer"},
        }
        conv_store.get_node = lambda node_id: node_map.get(node_id)

        trace_store = mock.MagicMock()
        trace_store.list_traces.return_value = []

        with mock.patch(
            "nova_ai.learning.training.dpo.DPOTrainer"
        ) as dpo_cls, mock.patch(
            "nova_ai.learning.training.lora.HAS_TORCH", True
        ):
            dpo_cls.return_value.train.return_value = {
                "status": "completed",
                "avg_loss": 0.1,
                "adapter_path": str(tmp_path / "adapter"),
            }
            record = run_training(
                trace_store=trace_store,
                config=_train_cfg(dpo_enabled=True, dpo_min_pairs=2, auto_apply=False),
                run_store=run_store,
                training_root=tmp_path / "root",
                lane="dpo",
                conv_store=conv_store,
            )
        assert record["status"] == "pending_review"
        assert record["lane"] == "dpo"
        assert dpo_cls.return_value.train.call_count == 1
        trained_pairs = dpo_cls.return_value.train.call_args[0][0]
        assert all(p["chosen"] == "good answer" for p in trained_pairs)

    def test_dpo_adapter_dir_suffix(self, env) -> None:
        """lane=dpo writes metadata with the lane marker."""
        run_store, tmp_path = env
        conv_store = _FakeConvStore([])
        trace_store = mock.MagicMock()
        trace_store.list_traces.return_value = []
        record = run_training(
            trace_store=trace_store,
            config=_train_cfg(dpo_enabled=True, dpo_min_pairs=1),
            run_store=run_store,
            training_root=tmp_path / "root",
            lane="dpo",
            conv_store=conv_store,
        )
        assert record["status"] == "failed"
        assert "lane=dpo: only 0" in record["error"]


# ---------------------------------------------------------------------------
# Store lane column
# ---------------------------------------------------------------------------


class TestStoreLane:
    def test_start_run_records_lane(self, tmp_path: Path) -> None:
        store = TrainingRunStore(tmp_path / "runs.db")
        try:
            store.start_run("r1", lane="dpo")
            store.finish_run("r1", status="failed", error="x")
            assert store.get_run("r1")["lane"] == "dpo"
            store.start_run("r2")
            assert store.get_run("r2")["lane"] == "sft"
        finally:
            store.close()

    def test_legacy_db_gets_lane_column(self, tmp_path: Path) -> None:
        """A pre-lane DB (old schema) is migrated on open."""
        import sqlite3

        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE training_runs (id TEXT PRIMARY KEY, status TEXT NOT NULL, "
            "trigger TEXT NOT NULL DEFAULT 'manual', base_model TEXT NOT NULL DEFAULT '', "
            "pairs INTEGER NOT NULL DEFAULT 0, avg_loss REAL, adapter_path TEXT, "
            "deploy_results TEXT NOT NULL DEFAULT '[]', benchmark_before REAL, "
            "benchmark_after REAL, benchmark_delta REAL, started_at TEXT NOT NULL, "
            "ended_at TEXT, error TEXT)"
        )
        conn.commit()
        conn.close()

        store = TrainingRunStore(db)
        try:
            store.start_run("legacy1", lane="dpo")
            assert store.get_run("legacy1")["lane"] == "dpo"
        finally:
            store.close()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestDPOConfig:
    def test_training_config_defaults(self) -> None:
        cfg = TrainingConfig()
        assert cfg.dpo_enabled is False
        assert cfg.dpo_min_pairs == 20
        assert cfg.dpo_tag_prefix == "nova-dpo"
