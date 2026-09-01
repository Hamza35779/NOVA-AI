"""LoRA fine-tuning applier — the real implementation of LORA_FINETUNE.

The v1 stub (``lora_stub.py``) refused this op with a "deferred to v2"
message. This applier makes the op real: it mines SFT pairs from the
trace store, runs the LoRA trainer, saves the adapter under the
spec-search session, and — when the risk gate allows (``auto_apply``) —
updates the active-adapter pointer.

Weight updates remain the most invasive edit class: the op stays pinned
at MANUAL tier in ``plan/risk_tier.py``. In TIERED/MANUAL autonomy the
execute loop routes it to review before this applier ever runs; only an
explicit ``auto_apply`` (or an auto-mode session) reaches ``apply()``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from nova_ai.learning.spec_search.execute.base import (
    ApplyContext,
    ApplyResult,
    EditApplier,
    ValidationResult,
)
from nova_ai.learning.spec_search.models import Edit, EditOp

logger = logging.getLogger(__name__)

_META_FILENAME = "adapter_meta.json"
_ACTIVE_FILENAME = "active.json"


class LoraFinetuneApplier(EditApplier):
    """Fine-tune a LoRA adapter from traces for a LORA_FINETUNE edit.

    Payload schema::

        {"target_model": "qwen3:8b", "focus_note": "optional context"}

    ``target_model`` names the base model to adapt. ``focus_note`` is
    teacher context recorded in the adapter metadata; it does not filter
    training data (trace mining is quality-threshold based).
    """

    op = EditOp.LORA_FINETUNE

    def __init__(
        self,
        *,
        learning_config: Optional[Any] = None,
        trace_store: Optional[Any] = None,
        sft_trainer_factory: Optional[Any] = None,
    ) -> None:
        self._learning_config = learning_config
        self._trace_store = trace_store
        self._sft_trainer_factory = sft_trainer_factory
        self._pre_apply_active: Optional[dict[str, Any]] = None

    # -- Config / dependency resolution --------------------------------------

    def _effective_config(self) -> Any:
        """Training config, honoring the deprecated flat aliases."""
        if self._learning_config is not None:
            return self._learning_config
        try:
            from nova_ai.core.config import load_config

            return load_config().learning
        except Exception as exc:
            logger.debug("Could not load learning config: %s", exc)
            return None

    def _resolve_trace_store(self, ctx: ApplyContext) -> Optional[Any]:
        if self._trace_store is not None:
            return self._trace_store
        try:
            from nova_ai.traces.store import TraceStore

            return TraceStore(ctx.nova_ai_home / "traces.db")
        except Exception as exc:
            logger.warning("Could not open TraceStore at %s: %s", ctx.nova_ai_home, exc)
            return None

    def _training_root(self, ctx: ApplyContext) -> Path:
        return ctx.nova_ai_home / "learning" / "training"

    # -- EditApplier ---------------------------------------------------------

    def validate(self, edit: Edit, ctx: ApplyContext) -> ValidationResult:
        target_model = edit.payload.get("target_model")
        if not target_model:
            return ValidationResult(
                ok=False, reason="Missing target_model in payload"
            )

        try:
            from nova_ai.learning.training.lora import HAS_TORCH

            if not HAS_TORCH:
                return ValidationResult(
                    ok=False,
                    reason="torch not available. Install with: "
                    "pip install torch transformers peft",
                )
        except ImportError:
            return ValidationResult(
                ok=False, reason="training.lora not importable"
            )

        config = self._effective_config()
        training_cfg = (
            config.training_effective if config is not None else None
        )
        min_pairs = training_cfg.min_pairs if training_cfg is not None else 50

        trace_store = self._resolve_trace_store(ctx)
        if trace_store is None:
            return ValidationResult(
                ok=False, reason="TraceStore unavailable; cannot mine SFT pairs"
            )

        try:
            from nova_ai.learning.training.data import TrainingDataMiner

            miner = TrainingDataMiner(trace_store, min_quality=0.7)
            pair_count = len(miner.extract_sft_pairs())
        except Exception as exc:
            return ValidationResult(
                ok=False, reason=f"trace mining failed: {exc}"
            )

        if pair_count < min_pairs:
            return ValidationResult(
                ok=False,
                reason=f"only {pair_count} qualifying SFT pairs, "
                f"need {min_pairs}",
            )
        return ValidationResult(ok=True)

    def apply(self, edit: Edit, ctx: ApplyContext) -> ApplyResult:
        target_model = edit.payload["target_model"]
        training_root = self._training_root(ctx)
        adapter_dir = training_root / "adapters" / f"session_{ctx.session_id}"

        # Capture the pre-apply active pointer for rollback.
        self._pre_apply_active = self._read_active(training_root)

        from nova_ai.learning.training.data import TrainingDataMiner

        trace_store = self._resolve_trace_store(ctx)
        if trace_store is None:
            raise RuntimeError("TraceStore unavailable")

        miner = TrainingDataMiner(trace_store, min_quality=0.7)
        pairs = miner.extract_sft_pairs()

        config = self._effective_config()
        training_cfg = config.training_effective if config is not None else None
        if training_cfg is not None and len(pairs) > training_cfg.max_pairs:
            pairs = pairs[: training_cfg.max_pairs]

        from nova_ai.core.config import SFTConfig

        sft_cfg = SFTConfig(
            model_name=target_model,
            checkpoint_dir=str(adapter_dir),
            min_pairs=training_cfg.min_pairs if training_cfg is not None else 50,
        )

        if self._sft_trainer_factory is not None:
            trainer = self._sft_trainer_factory(sft_cfg)
        else:
            from nova_ai.learning.intelligence.sft_trainer import SFTTrainer

            trainer = SFTTrainer(sft_cfg)

        result = trainer.train_on_pairs(pairs)
        if result.get("status") == "error":
            raise RuntimeError(
                f"LoRA training failed: {result.get('reason', 'unknown')}"
            )
        if result.get("status") == "skipped":
            raise RuntimeError(
                f"LoRA training skipped: {result.get('reason', 'no data')}"
            )

        adapter_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "session_id": ctx.session_id,
            "edit_id": edit.id,
            "base_model": target_model,
            "pairs": len(pairs),
            "avg_loss": result.get("avg_loss"),
            "focus_note": edit.payload.get("focus_note", ""),
            "rationale": edit.rationale,
            "applied_at": datetime.now(timezone.utc).isoformat(),
        }
        meta_path = adapter_dir / _META_FILENAME
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

        changed = [str(meta_path)]
        adapter_out = result.get("adapter_path")
        if adapter_out:
            changed.append(str(adapter_out))

        # Auto-apply: point the active adapter at the new one. Without this
        # (the default MANUAL-tier path) the adapter waits for explicit
        # promotion via `nova train deploy`.
        auto_apply = getattr(training_cfg, "auto_apply", False) if training_cfg else False
        if auto_apply:
            pointer = training_root / _ACTIVE_FILENAME
            pointer.write_text(
                json.dumps(
                    {
                        "adapter_path": str(adapter_dir.resolve()),
                        "base_model": target_model,
                        "session_id": ctx.session_id,
                        "run_id": edit.id,
                        "promoted_at": meta["applied_at"],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            changed.append(str(pointer))

        logger.info(
            "LoRA adapter trained at %s (pairs=%d, loss=%s, auto_apply=%s)",
            adapter_dir,
            len(pairs),
            result.get("avg_loss"),
            auto_apply,
        )
        return ApplyResult(changed_files=changed)

    def rollback(self, edit: Edit, ctx: ApplyContext) -> None:
        """Restore the pre-apply active pointer (disk-level rollback).

        The adapter directory itself is left in place — checkpoints are the
        session-level undo (Checkpointer), and a re-apply can reuse the
        artifact. Only the activation state is reverted here.
        """
        training_root = self._training_root(ctx)
        pointer = training_root / _ACTIVE_FILENAME
        if self._pre_apply_active is not None:
            pointer.write_text(
                json.dumps(self._pre_apply_active, indent=2) + "\n",
                encoding="utf-8",
            )
        elif pointer.exists():
            pointer.unlink()

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _read_active(training_root: Path) -> Optional[dict[str, Any]]:
        pointer = training_root / _ACTIVE_FILENAME
        if not pointer.exists():
            return None
        try:
            with open(pointer, encoding="utf-8") as f:
                return dict(json.load(f))  # type: ignore[arg-type]
        except (json.JSONDecodeError, OSError):
            return None


__all__ = ["LoraFinetuneApplier"]
