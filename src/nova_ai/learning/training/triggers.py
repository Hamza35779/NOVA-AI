"""Training triggers: auto-fire and scheduler wiring.

Three ways a training run starts, all funneling into
``pipeline.run_training``:

1. **Manual** — ``nova train run`` (see ``nova_ai.cli.train_cmd``).
2. **Scheduled** — a cron task derived from ``[learning.training] schedule``.
3. **Auto** — enough new qualifying traces accrued since the last
   successful run (``auto_trigger`` + ``auto_update``).

The auto-trigger deliberately requires *both* ``learning.auto_update``
(the global learning autonomy switch) and ``learning.training.auto_trigger``
(the training-specific switch) so an over-eager single flag can't start
rewriting weights.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def count_new_pairs_since(
    trace_store: Any,
    *,
    since_iso: Optional[str] = None,
    min_quality: float = 0.7,
) -> int:
    """Count qualifying SFT pairs newer than *since_iso*.

    Mirrors ``TrainingDataMiner``'s quality filter (feedback ≥ min_quality,
    outcome == success). ``since_iso=None`` counts everything (no successful
    run yet).
    """
    from nova_ai.learning.training.data import TrainingDataMiner

    miner = TrainingDataMiner(trace_store, min_quality=min_quality)
    pairs = miner.extract_sft_pairs()
    if not since_iso:
        return len(pairs)

    # TrainingDataMiner doesn't expose timestamps; filter on the trace level.
    count = 0
    try:
        traces = trace_store.list_traces(limit=10000)
        seen_pairs = {(p["input"], p["output"]) for p in pairs}
        for t in traces:
            if t.feedback is None or t.feedback < min_quality:
                continue
            if t.outcome != "success":
                continue
            if (t.query, t.result) not in seen_pairs:
                continue  # deduplicated away by the miner
            started = getattr(t, "started_at", None)
            started_iso = getattr(started, "isoformat", lambda: None)()
            if started_iso and started_iso <= since_iso:
                continue
            count += 1
    except Exception as exc:
        logger.warning("Could not count new pairs: %s", exc)
        return 0
    return count


def should_auto_trigger(
    *,
    trace_store: Any,
    run_store: Any,
    config: Any,
    learning_config: Any,
    min_quality: float = 0.7,
) -> tuple[bool, str]:
    """Decide whether an auto-triggered run should start.

    Returns ``(ok, reason)``. All of these must hold:

    - ``learning.auto_update`` and ``learning.training.auto_trigger`` are on
    - ``training.enabled`` is on
    - no run is currently in flight
    - new qualifying pairs since the last successful run ≥ ``min_pairs``
    """
    if not learning_config.auto_update:
        return False, "learning.auto_update is off"
    if not getattr(config, "enabled", False):
        return False, "learning.training.enabled is off"
    if not getattr(config, "auto_trigger", False):
        return False, "learning.training.auto_trigger is off"
    if run_store.is_running():
        return False, "a training run is already in flight"

    last = run_store.last_successful_run()
    since = last["ended_at"] if last else None
    new_pairs = count_new_pairs_since(
        trace_store, since_iso=since, min_quality=min_quality
    )
    if new_pairs < config.min_pairs:
        return False, (
            f"only {new_pairs} new pairs since last run "
            f"(need {config.min_pairs})"
        )
    return True, f"{new_pairs} new qualifying pairs"


def maybe_auto_trigger(
    *,
    trace_store: Any,
    run_store: Any,
    config: Any,
    learning_config: Any,
    training_root: Any = None,
    min_improvement: float = 0.02,
) -> Optional[dict[str, Any]]:
    """Run ``pipeline.run_training`` if ``should_auto_trigger`` passes.

    Returns the run record, or ``None`` when the trigger didn't fire.
    """
    ok, reason = should_auto_trigger(
        trace_store=trace_store,
        run_store=run_store,
        config=config,
        learning_config=learning_config,
    )
    if not ok:
        logger.debug("Auto-trigger not firing: %s", reason)
        return None

    from nova_ai.learning.training.pipeline import run_training

    logger.info("Auto-trigger firing: %s", reason)
    return run_training(
        trace_store=trace_store,
        config=config,
        run_store=run_store,
        training_root=training_root,
        trigger="auto",
        min_improvement=min_improvement,
        # Auto runs always carry a benchmark gate when one is wired; the
        # caller (daemon/learning loop) supplies benchmark_runner via config.
    )


def scheduled_task_metadata() -> dict[str, Any]:
    """Metadata marker for the scheduler's training task.

    The daemon's TaskScheduler dispatches tasks whose
    ``metadata["kind"] == "train"`` to ``run_scheduled_training`` instead of
    the agent query path.
    """
    return {"kind": "train"}


def run_scheduled_training(
    *,
    trace_store: Any,
    config: Any,
    run_store: Any,
    training_root: Any = None,
    min_improvement: float = 0.02,
    benchmark_runner: Any = None,
) -> dict[str, Any]:
    """Entry point for the cron-driven nightly run."""
    from nova_ai.learning.training.pipeline import run_training

    return run_training(
        trace_store=trace_store,
        config=config,
        run_store=run_store,
        training_root=training_root,
        trigger="scheduled",
        min_improvement=min_improvement,
        benchmark_runner=benchmark_runner,
    )


__all__ = [
    "count_new_pairs_since",
    "maybe_auto_trigger",
    "run_scheduled_training",
    "scheduled_task_metadata",
    "should_auto_trigger",
]
