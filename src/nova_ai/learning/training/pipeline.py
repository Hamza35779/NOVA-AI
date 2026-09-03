"""End-to-end self-training pipeline: mine traces → LoRA → gate → deploy.

One entry point, ``run_training()``, shared by every trigger:

* ``nova train run`` (CLI, foreground or background)
* the cron task created from ``[learning.training] schedule``
* the auto-trigger when enough new qualifying traces accrue

Safety model (weight updates are the most invasive edit class — spec-search
pins ``LORA_FINETUNE`` at MANUAL tier):

1. The benchmark gate scores the base and tuned models on the personal
   benchmark. A delta below ``learning.min_improvement`` rolls the run back
   — the adapter is recorded but never becomes active or deployed.
2. Without ``auto_apply``, a passing run lands in ``pending_review``: the
   adapter exists, ``active.json`` is untouched, and promotion is a manual
   ``nova train deploy``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from nova_ai.core.config import TrainingConfig
from nova_ai.learning.training.data import TrainingDataMiner
from nova_ai.learning.training.deploy import deploy
from nova_ai.learning.training.store import TrainingRunStore

logger = logging.getLogger(__name__)

TERMINAL_STATES = ("completed", "pending_review", "rolled_back", "failed")


def _default_training_root() -> Path:
    """Root for adapters/active pointer, under the NOVA AI home."""
    from nova_ai.core.paths import get_config_dir

    return get_config_dir() / "learning" / "training"


def _sanitize(name: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")


def active_adapter_path(training_root: Path) -> Optional[Path]:
    """Return the currently active adapter directory, if any."""
    pointer = training_root / "active.json"
    if not pointer.exists():
        return None
    import json

    try:
        with open(pointer, encoding="utf-8") as f:
            data = json.load(f)
        path = Path(data.get("adapter_path", ""))
        return path if path.exists() else None
    except (json.JSONDecodeError, OSError):
        return None


def promote_adapter(
    adapter_dir: Path,
    *,
    training_root: Path,
    base_model: str,
    run_id: str = "",
) -> Path:
    """Point ``active.json`` at an adapter (manual promotion path).

    Used by ``nova train deploy`` to promote a pending_review adapter.
    """
    import json

    training_root = Path(training_root)
    training_root.mkdir(parents=True, exist_ok=True)
    pointer = training_root / "active.json"

    payload = {
        "adapter_path": str(Path(adapter_dir).resolve()),
        "base_model": base_model,
        "run_id": run_id,
        "promoted_at": datetime.now(timezone.utc).isoformat(),
    }
    pointer.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return pointer


def run_training(
    *,
    trace_store: Any,
    config: TrainingConfig,
    run_store: TrainingRunStore,
    training_root: Optional[Path] = None,
    trigger: str = "manual",
    base_model: Optional[str] = None,
    benchmark_runner: Optional[Any] = None,
    auto_apply: Optional[bool] = None,
    min_improvement: float = 0.02,
    lane: str = "sft",
    conv_store: Optional[Any] = None,
) -> dict[str, Any]:
    """Mine traces, fine-tune, gate on the benchmark, and deploy.

    Parameters
    ----------
    trace_store :
        Object with ``list_traces()`` (typically ``TraceStore``).
    config :
        ``[learning.training]`` settings.
    run_store :
        Persistence for the run record.
    training_root :
        Root for adapters + active pointer (default ``~/.nova_ai/learning/training``).
    trigger :
        What started this run (``manual`` | ``scheduled`` | ``auto``).
    base_model :
        HF identifier or local path for the base model. ``None`` uses the
        SFT default (``Qwen/Qwen3-1.7B``).
    benchmark_runner :
        Optional callable ``(model_name) -> float`` scoring a model on the
        personal benchmark. ``None`` skips the gate (manual runs may
        consciously opt out; scheduled/auto runs should always pass one).
    auto_apply :
        Override for ``config.auto_apply`` (the applier passes the
        LearningConfig-level flag).
    min_improvement :
        Benchmark delta required to keep the adapter.
    lane :
        ``"sft"`` (default) or ``"dpo"``. The DPO lane trains on
        *preference pairs* (chosen vs rejected answers from conversation
        forks/regens/races, plus trace-derived signals) instead of
        SFT pairs, saves under ``adapters/<run_id>/dpo``, and deploys
        with ``config.dpo_tag_prefix`` Ollama tags.
    conv_store :
        ``ConversationStore`` (P3) supplying recorded preference pairs.
        Required for ``lane="dpo"`` unless ``config.dpo_enabled`` is off.

    Returns
    -------
    dict
        The final run record (same shape as ``TrainingRunStore.get_run``).
    """
    training_root = Path(training_root) if training_root else _default_training_root()
    run_id = f"train_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    lane = "dpo" if lane == "dpo" else "sft"

    resolved_base = base_model or _default_base_model()
    run_store.start_run(run_id, trigger=trigger, base_model=resolved_base, lane=lane)

    def _fail(error: str, **fields: Any) -> dict[str, Any]:
        run_store.finish_run(run_id, status="failed", error=error, **fields)
        record = run_store.get_run(run_id) or {}
        logger.warning("Training run %s failed: %s", run_id, error)
        return record

    # 1. Mine training data -----------------------------------------------------
    if lane == "dpo":
        try:
            from nova_ai.learning.training.data import extract_preference_pairs

            if conv_store is None:
                from nova_ai.conversations.store import ConversationStore
                from nova_ai.core.config import DEFAULT_CONFIG_DIR

                conv_store = ConversationStore(
                    Path(DEFAULT_CONFIG_DIR) / "conversations.db"
                )
            pairs = extract_preference_pairs(
                conv_store, trace_store=trace_store, min_quality=0.7
            )
        except Exception as exc:
            return _fail(f"preference mining failed: {exc}")
        min_required = config.dpo_min_pairs
        lane_dirname = "dpo"
    else:
        try:
            miner = TrainingDataMiner(trace_store, min_quality=0.7)
            pairs = miner.extract_sft_pairs()
        except Exception as exc:
            return _fail(f"trace mining failed: {exc}")
        min_required = config.min_pairs
        lane_dirname = "sft"

    if len(pairs) < min_required:
        return _fail(
            f"lane={lane}: only {len(pairs)} qualifying pairs, "
            f"min={min_required}"
        )
    pairs = pairs[: config.max_pairs]

    # 2. Benchmark the base model (pre) --------------------------------------
    pre_score: Optional[float] = None
    if benchmark_runner is not None:
        try:
            pre_score = float(benchmark_runner(resolved_base))
        except Exception as exc:
            logger.warning("Pre-training benchmark failed (%s); gate disabled", exc)
            pre_score = None

    # 3. Train ---------------------------------------------------------------
    adapter_dir = training_root / "adapters" / run_id / lane_dirname
    try:
        from nova_ai.core.config import SFTConfig
        from nova_ai.learning.training.lora import HAS_TORCH

        if not HAS_TORCH:
            return _fail(
                "torch not available; install with: "
                "pip install torch transformers peft"
                + (" trl" if lane == "dpo" else "")
            )

        if lane == "dpo":
            from nova_ai.learning.training.dpo import DPOTrainer, DPOTrainingConfig

            dpo_cfg = DPOTrainingConfig(output_dir=str(adapter_dir / "final"))
            trainer = DPOTrainer(dpo_cfg, model_name=resolved_base)
            result = trainer.train(pairs)
        else:
            sft_cfg = SFTConfig(
                model_name=resolved_base,
                checkpoint_dir=str(adapter_dir),
                min_pairs=config.min_pairs,
            )
            from nova_ai.learning.intelligence.sft_trainer import SFTTrainer

            trainer = SFTTrainer(sft_cfg)
            result = trainer.train_on_pairs(pairs)
    except Exception as exc:
        return _fail(f"training failed: {exc}")

    if result.get("status") not in ("completed", "skipped"):
        return _fail(
            f"training returned status={result.get('status')!r}: "
            f"{result.get('reason', result.get('error', 'unknown'))}"
        )
    if result.get("status") == "skipped":
        return _fail(f"training skipped: {result.get('reason', 'no data')}")

    avg_loss = result.get("avg_loss")
    adapter_out = Path(result.get("adapter_path") or adapter_dir / "final")

    # Persist metadata alongside the adapter for deploy/rollback.
    import json

    adapter_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "run_id": run_id,
        "lane": lane,
        "base_model": resolved_base,
        "pairs": len(pairs),
        "avg_loss": avg_loss,
        "trigger": trigger,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = adapter_dir / "adapter_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    # The trainer may have saved to its own path; normalize the record to our
    # canonical location while keeping the trainer's output intact.
    adapter_record_path = str(adapter_out if adapter_out.exists() else adapter_dir)

    # 4. Benchmark gate ------------------------------------------------------
    post_score: Optional[float] = None
    if benchmark_runner is not None and pre_score is not None:
        try:
            post_score = float(benchmark_runner(adapter_record_path))
        except Exception as exc:
            logger.warning("Post-training benchmark failed (%s)", exc)

    delta: Optional[float] = None
    if pre_score is not None and post_score is not None:
        delta = post_score - pre_score
        if delta < min_improvement:
            run_store.finish_run(
                run_id,
                status="rolled_back",
                pairs=len(pairs),
                avg_loss=avg_loss,
                adapter_path=adapter_record_path,
                benchmark_before=pre_score,
                benchmark_after=post_score,
                benchmark_delta=delta,
                error=(
                    f"benchmark delta {delta:+.4f} below min_improvement "
                    f"{min_improvement}; adapter not activated or deployed"
                ),
            )
            record = run_store.get_run(run_id) or {}
            logger.warning(
                "Training run %s rolled back (delta %+.4f < %s)",
                run_id,
                delta,
                min_improvement,
            )
            return record

    # 5. Deploy --------------------------------------------------------------
    apply = config.auto_apply if auto_apply is None else auto_apply
    deploy_results: list[dict[str, Any]] = []
    tag_prefix = (
        config.dpo_tag_prefix if lane == "dpo" else config.ollama_tag_prefix
    )
    if apply:
        report = deploy(
            Path(adapter_record_path),
            targets=config.deploy_targets,
            base_model=resolved_base,
            tag_prefix=tag_prefix,
            gguf_script=config.llamacpp_gguf_script,
        )
        deploy_results = report.to_list()
        status = "completed" if report.ok else "failed"
        error = None if report.ok else "all deployment targets failed"
    else:
        status = "pending_review"
        error = None

    run_store.finish_run(
        run_id,
        status=status,
        pairs=len(pairs),
        avg_loss=avg_loss,
        adapter_path=adapter_record_path,
        deploy_results=deploy_results,
        benchmark_before=pre_score,
        benchmark_after=post_score,
        benchmark_delta=delta,
        error=error,
    )
    record = run_store.get_run(run_id) or {}
    record["lane"] = lane
    logger.info("Training run %s finished: %s (lane=%s)", run_id, status, lane)
    return record


def _default_base_model() -> str:
    """Default base model, from SFT config."""
    from nova_ai.core.config import SFTConfig

    return SFTConfig().model_name


__all__ = [
    "TERMINAL_STATES",
    "active_adapter_path",
    "promote_adapter",
    "run_training",
]
