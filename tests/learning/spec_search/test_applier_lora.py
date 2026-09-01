"""Tests for LoraFinetuneApplier — the real LORA_FINETUNE applier.

All tests run torch-free: ``apply()`` paths that need torch are exercised
via a fake SFT trainer injected through ``sft_trainer_factory`` (the same
seam the real pipeline uses), and the torch-gate is tested by pointing the
applier's config at a stubbed module.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nova_ai.learning.spec_search.execute.appliers.lora import LoraFinetuneApplier
from nova_ai.learning.spec_search.execute.base import ApplyContext
from nova_ai.learning.spec_search.models import (
    Edit,
    EditOp,
    EditPillar,
    EditRiskTier,
)


def _make_edit(**payload_overrides) -> Edit:
    payload = {"target_model": "qwen3:8b", "focus_note": "math"}
    payload.update(payload_overrides)
    return Edit(
        id="edit-lora",
        pillar=EditPillar.INTELLIGENCE,
        op=EditOp.LORA_FINETUNE,
        target="models.qwen3:8b",
        payload=payload,
        rationale="Fine-tune for math",
        expected_improvement="cluster-001",
        risk_tier=EditRiskTier.MANUAL,
    )


def _make_ctx(tmp_path: Path) -> ApplyContext:
    return ApplyContext(nova_ai_home=tmp_path, session_id="s1")


def _make_applier(tmp_path: Path, *, pairs: int = 100, auto_apply: bool = False):
    """Applier with mocked config + trace store; torch checks pass."""
    trace_store = MagicMock()
    trace_store.list_traces.return_value = []

    learning_cfg = MagicMock()
    learning_cfg.training_effective.min_pairs = 10
    learning_cfg.training_effective.max_pairs = 5000
    learning_cfg.training_effective.auto_apply = auto_apply

    applier = LoraFinetuneApplier(
        learning_config=learning_cfg,
        trace_store=trace_store,
    )
    return applier


# This environment has no torch; the applier (correctly) refuses everything.
# Tests that exercise validate/apply happy paths patch the torch gate.
_TORCH_OK = patch("nova_ai.learning.training.lora.HAS_TORCH", True)


def _seed_pairs(tmp_path: Path, n: int = 100) -> None:
    """Patch TrainingDataMiner to return n pairs without touching sqlite."""
    pairs = [
        {"input": f"q{i}", "output": f"a{i}", "query_class": "math",
         "model": "qwen3:8b", "feedback": 0.9}
        for i in range(n)
    ]
    patcher = patch(
        "nova_ai.learning.training.data.TrainingDataMiner.extract_sft_pairs",
        return_value=pairs,
    )
    patcher.start()
    return None


class TestValidate:
    def test_missing_target_model(self, tmp_path: Path) -> None:
        applier = _make_applier(tmp_path)
        result = applier.validate(_make_edit(target_model=None), _make_ctx(tmp_path))
        assert not result.ok
        assert "target_model" in result.reason

    def test_torch_missing_rejects(self, tmp_path: Path) -> None:
        applier = _make_applier(tmp_path)
        with patch(
            "nova_ai.learning.training.lora.HAS_TORCH", False
        ):
            result = applier.validate(_make_edit(), _make_ctx(tmp_path))
        assert not result.ok
        assert "torch" in result.reason.lower()

    def test_insufficient_pairs_rejects(self, tmp_path: Path) -> None:
        applier = _make_applier(tmp_path)
        p = patch(
            "nova_ai.learning.training.data.TrainingDataMiner.extract_sft_pairs",
            return_value=[{"input": "q", "output": "a"}],
        )
        with _TORCH_OK, p:
            result = applier.validate(_make_edit(), _make_ctx(tmp_path))
        assert not result.ok
        assert "1 qualifying" in result.reason

    def test_enough_pairs_passes(self, tmp_path: Path) -> None:
        applier = _make_applier(tmp_path)
        pairs = [{"input": f"q{i}", "output": f"a{i}"} for i in range(20)]
        with patch(
            "nova_ai.learning.training.data.TrainingDataMiner.extract_sft_pairs",
            return_value=pairs,
        ), _TORCH_OK:
            result = applier.validate(_make_edit(), _make_ctx(tmp_path))
        assert result.ok


class TestApply:
    def _trainer_result(self) -> dict:
        return {
            "status": "completed",
            "avg_loss": 0.42,
            "adapter_path": "unused",
            "training_samples": 100,
        }

    def test_apply_trains_and_writes_meta(self, tmp_path: Path) -> None:
        applier = _make_applier(tmp_path)

        fake_trainer = MagicMock()
        fake_trainer.train_on_pairs.return_value = self._trainer_result()
        applier._sft_trainer_factory = lambda cfg: fake_trainer

        with patch(
            "nova_ai.learning.training.data.TrainingDataMiner.extract_sft_pairs",
            return_value=[{"input": "q", "output": "a"}] * 100,
        ):
            result = applier.apply(_make_edit(), _make_ctx(tmp_path))

        fake_trainer.train_on_pairs.assert_called_once()
        assert fake_trainer.train_on_pairs.call_args[0][0][0]["input"] == "q"

        meta_path = (
            tmp_path / "learning" / "training" / "adapters" / "session_s1"
            / "adapter_meta.json"
        )
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["base_model"] == "qwen3:8b"
        assert meta["session_id"] == "s1"
        assert "adapter_meta.json" in " ".join(result.changed_files)

    def test_apply_error_status_raises(self, tmp_path: Path) -> None:
        applier = _make_applier(tmp_path)
        fake_trainer = MagicMock()
        fake_trainer.train_on_pairs.return_value = {
            "status": "error", "reason": "boom",
        }
        applier._sft_trainer_factory = lambda cfg: fake_trainer

        with patch(
            "nova_ai.learning.training.data.TrainingDataMiner.extract_sft_pairs",
            return_value=[{"input": "q", "output": "a"}] * 100,
        ):
            with pytest.raises(RuntimeError, match="boom"):
                applier.apply(_make_edit(), _make_ctx(tmp_path))

    def test_auto_apply_updates_active_pointer(self, tmp_path: Path) -> None:
        applier = _make_applier(tmp_path, auto_apply=True)
        fake_trainer = MagicMock()
        fake_trainer.train_on_pairs.return_value = self._trainer_result()
        applier._sft_trainer_factory = lambda cfg: fake_trainer

        with patch(
            "nova_ai.learning.training.data.TrainingDataMiner.extract_sft_pairs",
            return_value=[{"input": "q", "output": "a"}] * 100,
        ):
            applier.apply(_make_edit(), _make_ctx(tmp_path))

        pointer = tmp_path / "learning" / "training" / "active.json"
        assert pointer.exists()
        data = json.loads(pointer.read_text(encoding="utf-8"))
        assert data["base_model"] == "qwen3:8b"
        assert data["session_id"] == "s1"

    def test_no_auto_apply_leaves_pointer_absent(self, tmp_path: Path) -> None:
        applier = _make_applier(tmp_path, auto_apply=False)
        fake_trainer = MagicMock()
        fake_trainer.train_on_pairs.return_value = self._trainer_result()
        applier._sft_trainer_factory = lambda cfg: fake_trainer

        with patch(
            "nova_ai.learning.training.data.TrainingDataMiner.extract_sft_pairs",
            return_value=[{"input": "q", "output": "a"}] * 100,
        ):
            applier.apply(_make_edit(), _make_ctx(tmp_path))

        pointer = tmp_path / "learning" / "training" / "active.json"
        assert not pointer.exists()


class TestRollback:
    def _trainer_result(self) -> dict:
        return {
            "status": "completed",
            "avg_loss": 0.42,
            "adapter_path": "unused",
            "training_samples": 100,
        }

    def test_rollback_restores_previous_pointer(self, tmp_path: Path) -> None:
        applier = _make_applier(tmp_path, auto_apply=True)
        fake_trainer = MagicMock()
        fake_trainer.train_on_pairs.return_value = self._trainer_result()
        applier._sft_trainer_factory = lambda cfg: fake_trainer

        # Pre-existing active adapter
        training_root = tmp_path / "learning" / "training"
        training_root.mkdir(parents=True)
        previous = {
            "adapter_path": "/old/adapter",
            "base_model": "old-model",
        }
        (training_root / "active.json").write_text(json.dumps(previous))

        with patch(
            "nova_ai.learning.training.data.TrainingDataMiner.extract_sft_pairs",
            return_value=[{"input": "q", "output": "a"}] * 100,
        ):
            applier.apply(_make_edit(), _make_ctx(tmp_path))

        applier.rollback(_make_edit(), _make_ctx(tmp_path))
        restored = json.loads(
            (training_root / "active.json").read_text(encoding="utf-8")
        )
        assert restored == previous

    def test_rollback_removes_pointer_when_none_before(self, tmp_path: Path) -> None:
        applier = _make_applier(tmp_path, auto_apply=True)
        fake_trainer = MagicMock()
        fake_trainer.train_on_pairs.return_value = self._trainer_result()
        applier._sft_trainer_factory = lambda cfg: fake_trainer

        with patch(
            "nova_ai.learning.training.data.TrainingDataMiner.extract_sft_pairs",
            return_value=[{"input": "q", "output": "a"}] * 100,
        ):
            applier.apply(_make_edit(), _make_ctx(tmp_path))

        pointer = tmp_path / "learning" / "training" / "active.json"
        assert pointer.exists()
        applier.rollback(_make_edit(), _make_ctx(tmp_path))
        assert not pointer.exists()


class TestRegistry:
    def test_registry_registers_real_applier_with_torch_stub_without(self) -> None:
        """With torch available the real applier wins; without, the stub."""
        from nova_ai.learning.spec_search.execute.appliers.lora import (
            LoraFinetuneApplier as Real,
        )
        from nova_ai.learning.spec_search.execute.appliers.lora_stub import (
            LoraStubApplier as Stub,
        )
        from nova_ai.learning.spec_search.execute.loop import _build_registry
        from nova_ai.learning.training.lora import HAS_TORCH

        registry = _build_registry()
        applier = registry.get(EditOp.LORA_FINETUNE)
        if HAS_TORCH:
            assert isinstance(applier, Real)
        else:
            assert isinstance(applier, Stub)
