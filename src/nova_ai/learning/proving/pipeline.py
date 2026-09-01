"""Head-to-head proving pipeline: synthesize → eval both → per-class verdict.

One entry point, ``run_proving()``, shared by every trigger:

* ``nova prove run`` (CLI, foreground or background)
* the scheduler task (``metadata["kind"] == "prove"``)
* the auto-trigger when a new model appears (``watcher.maybe_auto_prove``)

Fairness rules:

* Both models answer the *same* benchmark — samples synthesized once from
  high-feedback traces — with the same seed, temperature 0, and the *same*
  judge model (default: the incumbent itself, so no third model decides).
* Per query class, a verdict requires at least 3 scored samples on both
  sides, and adoption additionally requires ``min_margin``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from nova_ai.core.config import ProvingConfig
from nova_ai.learning.proving.store import ProvingRunStore

logger = logging.getLogger(__name__)

# Classes with fewer scored samples than this are reported but never
# assigned a winner — too little evidence.
MIN_SCORED_PER_CLASS = 3


def _default_proving_root() -> Path:
    """Root for the policy map + watcher state, under the NOVA AI home."""
    from nova_ai.core.paths import get_config_dir

    return get_config_dir() / "learning" / "proving"


def _resolve_incumbent(config: ProvingConfig) -> str:
    """Incumbent: explicit config value, else the default model."""
    if config.incumbent:
        return config.incumbent
    try:
        from nova_ai.core.config import load_config

        return load_config().intelligence.default_model or ""
    except Exception as exc:
        logger.warning("Could not load default model for incumbent: %s", exc)
        return ""


def _available_models(config_obj: Optional[Any]) -> Optional[set[str]]:
    """All model ids visible across healthy engines, or None on failure."""
    try:
        from nova_ai.learning.proving.watcher import list_local_models

        cfg = config_obj
        if cfg is None:
            from nova_ai.core.config import load_config

            cfg = load_config()
        return set(list_local_models(cfg))
    except Exception as exc:
        logger.warning("Model discovery failed; skipping servability check: %s", exc)
        return None


def _build_default_backend():
    """NovaDirectBackend used for both generation sides (no --base-url)."""
    from nova_ai.evals.backends.nova_direct import NovaDirectBackend

    return NovaDirectBackend()


def _build_judge(config: ProvingConfig, default_backend: Any):
    """Judge backend honoring ``judge_engine`` (local shares the eval backend)."""
    if (config.judge_engine or "local") == "local":
        return default_backend
    from nova_ai.evals.backends.nova_direct import NovaDirectBackend

    return NovaDirectBackend(engine_key="cloud")


def _scored_accuracy(summary: Any, qclass: str) -> Optional[tuple[float, int]]:
    """Accuracy and scored count for one query class, or None if absent."""
    entry = (summary.per_subject or {}).get(qclass)
    if not entry:
        return None
    scored = int(entry.get("scored", 0))
    return float(entry.get("accuracy", 0.0)), scored


class _QClassDataset:
    """PersonalBenchmarkDataset keyed by *routing* query class.

    The stock adapter sets ``EvalRecord.subject`` to the agent name; the
    proving ground needs the routing class (``code``/``math``/…), which is
    what ``RunSummary.per_subject`` then keys on. Wraps rather than
    subclasses ``load()`` so the stock adapter stays untouched.
    """

    dataset_id = "personal-qclass"
    dataset_name = "Personal Benchmark (per query class)"

    def __init__(self, benchmark: Any) -> None:
        from nova_ai.learning.optimize.personal.dataset import (
            PersonalBenchmarkDataset,
        )

        self._inner = PersonalBenchmarkDataset(benchmark)

    def load(self, *, max_samples: Any = None, split: Any = None, seed: Any = None) -> None:
        from nova_ai.learning.routing._utils import classify_query

        self._inner.load(max_samples=max_samples, split=split, seed=seed)
        for record in self._inner._records:
            record.subject = classify_query(record.problem)

    def iter_records(self) -> Any:
        return self._inner.iter_records()

    def size(self) -> int:
        return self._inner.size()


def run_proving(
    *,
    candidate: str,
    trace_store: Any,
    config: ProvingConfig,
    run_store: ProvingRunStore,
    incumbent: Optional[str] = None,
    proving_root: Optional[Path] = None,
    trigger: str = "manual",
    adopt: Optional[bool] = None,
    backend_factory: Optional[Any] = None,
    judge_backend: Optional[Any] = None,
    config_obj: Optional[Any] = None,
) -> dict[str, Any]:
    """Run the head-to-head gauntlet for *candidate* vs the incumbent.

    Parameters
    ----------
    candidate :
        Model id to challenge (e.g. a freshly pulled Ollama tag).
    trace_store :
        Object with ``list_traces(limit=...)`` (typically ``TraceStore``).
    config :
        ``[learning.proving]`` settings.
    run_store :
        Persistence for the run record.
    incumbent :
        Opponent model id. Default: config.incumbent or the configured
        default model.
    proving_root :
        Root for the policy map + watcher state
        (default ``~/.nova_ai/learning/proving``).
    trigger :
        What started this run (``manual`` | ``scheduled`` | ``auto``).
    adopt :
        Override for ``config.auto_adopt`` — write winners to the policy
        map without a later ``nova prove adopt``.
    backend_factory :
        Optional zero-arg callable returning the generation backend
        (``NovaDirectBackend`` by default). Test seam.
    judge_backend :
        Optional pre-built judge backend. Default: derived from
        ``judge_engine`` (local shares the generation backend).
    config_obj :
        Optional full ``NovaConfig`` for discovery (resolved lazily when
        omitted).

    Returns
    -------
    dict
        The final run record (same shape as ``ProvingRunStore.get_run``).
    """
    proving_root = Path(proving_root) if proving_root else _default_proving_root()
    run_id = (
        f"prove_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        f"_{uuid.uuid4().hex[:6]}"
    )

    resolved_incumbent = incumbent or _resolve_incumbent(config)

    def _fail(error: str) -> dict[str, Any]:
        run_store.finish_run(run_id, status="failed", error=error)
        record = run_store.get_run(run_id) or {}
        logger.warning("Proving run %s failed: %s", run_id, error)
        return record

    if not candidate:
        run_store.start_run(run_id, trigger=trigger, candidate="", incumbent=resolved_incumbent)
        return _fail("no candidate model given")

    if run_store.is_running():
        run_store.start_run(run_id, trigger=trigger, candidate=candidate, incumbent=resolved_incumbent)
        return _fail("another proving run is already in flight")

    if resolved_incumbent and candidate == resolved_incumbent:
        run_store.start_run(run_id, trigger=trigger, candidate=candidate, incumbent=resolved_incumbent)
        return _fail(
            f"candidate {candidate!r} is the incumbent; nothing to prove"
        )

    # 1. Servability check (fail fast with what IS available) ---------------
    available = _available_models(config_obj)
    if available:
        missing = [m for m in (candidate, resolved_incumbent) if m and m not in available]
        if missing:
            run_store.start_run(run_id, trigger=trigger, candidate=candidate, incumbent=resolved_incumbent)
            return _fail(
                f"model(s) not found on any engine: {', '.join(missing)}; "
                f"available: {', '.join(sorted(available)) or 'none'}"
            )

    run_store.start_run(
        run_id, trigger=trigger, candidate=candidate, incumbent=resolved_incumbent
    )

    # 2. Synthesize the shared benchmark ------------------------------------
    try:
        from nova_ai.learning.optimize.personal.synthesizer import (
            PersonalBenchmarkSynthesizer,
        )

        benchmark = PersonalBenchmarkSynthesizer(trace_store).synthesize(
            min_feedback=0.7, max_samples=config.max_samples
        )
    except Exception as exc:
        return _fail(f"benchmark synthesis failed: {exc}")

    if len(benchmark.samples) < config.min_samples:
        return _fail(
            f"not enough qualifying traces: {len(benchmark.samples)} < "
            f"min_samples={config.min_samples}"
        )

    # 3. Backends + judge ----------------------------------------------------
    try:
        if backend_factory is not None:
            backend = backend_factory()
        else:
            backend = _build_default_backend()
    except Exception as exc:
        return _fail(f"could not build generation backend: {exc}")

    if judge_backend is None:
        try:
            judge_backend = _build_judge(config, backend)
        except Exception as exc:
            return _fail(f"could not build judge backend: {exc}")
    judge_model = config.judge_model or resolved_incumbent or candidate

    # 4. Eval both sides on the same dataset ---------------------------------
    from nova_ai.evals.core.runner import EvalRunner
    from nova_ai.evals.core.types import RunConfig
    from nova_ai.learning.optimize.personal.scorer import PersonalBenchmarkScorer

    dataset = _QClassDataset(benchmark)
    scorer = PersonalBenchmarkScorer(judge_backend, judge_model)
    summaries: dict[str, Any] = {}
    for side, model in (("candidate", candidate), ("incumbent", resolved_incumbent)):
        run_cfg = RunConfig(
            benchmark="personal",
            backend="nova-direct",
            model=model,
            max_workers=4,
            temperature=0.0,
            seed=42,
        )
        try:
            summaries[side] = EvalRunner(
                run_cfg, dataset, backend, scorer
            ).run()
        except Exception as exc:
            return _fail(f"{side} eval failed ({model}): {exc}")

    # 5. Per-class verdicts --------------------------------------------------
    cand_summary = summaries["candidate"]
    inc_summary = summaries["incumbent"]
    per_class: dict[str, dict[str, Any]] = {}
    for qclass in sorted(
        set(cand_summary.per_subject or {}) | set(inc_summary.per_subject or {})
    ):
        cand = _scored_accuracy(cand_summary, qclass)
        inc = _scored_accuracy(inc_summary, qclass)
        entry: dict[str, Any] = {"total": (cand or inc)[1]}
        if cand is None or inc is None or cand[1] < MIN_SCORED_PER_CLASS or inc[1] < MIN_SCORED_PER_CLASS:
            entry.update(
                candidate_acc=cand[0] if cand else None,
                incumbent_acc=inc[0] if inc else None,
                delta=None,
                winner=None,
            )
            per_class[qclass] = entry
            continue
        delta = cand[0] - inc[0]
        entry.update(
            candidate_acc=cand[0],
            incumbent_acc=inc[0],
            delta=round(delta, 4),
            winner=None,
        )
        if delta >= config.min_margin:
            entry["winner"] = candidate
        elif -delta >= config.min_margin:
            entry["winner"] = resolved_incumbent
        per_class[qclass] = entry

    run_store.finish_run(
        run_id, status="completed", samples=len(benchmark.samples), per_class=per_class
    )

    # 6. Adoption (opt-in) ---------------------------------------------------
    adopted: dict[str, str] = {}
    apply = config.auto_adopt if adopt is None else adopt
    if apply:
        from nova_ai.learning.proving.adoption import adopt_winners

        adopted = adopt_winners(
            run_id=run_id,
            per_class=per_class,
            min_margin=config.min_margin,
            proving_root=proving_root,
        )
        if adopted:
            run_store.finish_run(
                run_id,
                status="completed",
                samples=len(benchmark.samples),
                per_class=per_class,
                adopted=adopted,
            )

    record = run_store.get_run(run_id) or {}
    logger.info("Proving run %s finished: %s", run_id, record.get("status"))
    return record


__all__ = ["MIN_SCORED_PER_CLASS", "run_proving"]
