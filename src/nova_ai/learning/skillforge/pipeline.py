"""The forge pipeline — mine → synthesize → gauntlet → (maybe) adopt.

One entry point, ``run_skillforge()``, shared by ``nova forge run``,
the scheduler task (``metadata["kind"] == "skillforge"``), and future
auto-triggers. Like train/prove, the forge never changes live behavior
on its own: candidates land in ``pending``/``passed`` state and only
``nova forge adopt`` (or ``auto_adopt``) installs them.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from nova_ai.learning.skillforge.miner import PatternMiner
from nova_ai.learning.skillforge.store import SkillForgeRunStore
from nova_ai.learning.skillforge.synthesizer import SkillSynthesizer, sanitize_name

logger = logging.getLogger(__name__)


def default_llm(config: Any) -> Any:
    """Build the production LLM backend for synthesis."""
    from nova_ai.evals.backends.nova_direct import NovaDirectBackend

    engine_key = getattr(config, "judge_engine", "") or "local"
    return NovaDirectBackend(engine_key=engine_key)


def run_skillforge(
    *,
    trace_store: Any,
    config: Any,
    run_store: SkillForgeRunStore,
    skills_root: Path,
    llm: Optional[Any] = None,
    tool_executor: Optional[Any] = None,
    judge: Optional[Any] = None,
    trigger: str = "manual",
) -> dict[str, Any]:
    """Run one forge cycle and return its summary.

    Parameters
    ----------
    trace_store :
        Object with ``list_traces(limit=...)`` (typically ``TraceStore``).
    config :
        ``[learning.skillforge]`` settings (``SkillForgeConfig``).
    run_store :
        Persistence for run records.
    skills_root :
        Root for adopted skills (``~/.nova_ai/skills``).
    llm :
        Injection seam for synthesis; ``generate(prompt) -> str``.
    tool_executor :
        Injection seam for replay (a ``ToolExecutor``).
    judge :
        Optional LLM judge for the final gate.
    trigger :
        What started this run (``manual`` | ``scheduled`` | ``auto``).
    """
    run_id = f"forge_{uuid.uuid4().hex[:12]}"

    def _fail(error: str) -> dict[str, Any]:
        logger.warning("[skillforge] failed: %s", error)
        run_store.finish_run(run_id, status="failed", error=error)
        return {"status": "failed", "run_id": run_id, "error": error}

    run_store.start_run(run_id, trigger=trigger)

    if not getattr(config, "enabled", False):
        return _fail("learning.skillforge.enabled is false")

    if llm is None:
        llm = default_llm(config)
    if tool_executor is None:
        return _fail("no tool executor available for replay")

    # 1. Mine ---------------------------------------------------------------
    miner = PatternMiner(
        trace_store,
        min_pattern_count=int(getattr(config, "min_pattern_count", 3)),
        min_feedback=float(getattr(config, "min_feedback", 0.7)),
    )
    patterns = miner.mine()
    if not patterns:
        run_store.finish_run(run_id, status="completed")
        return {
            "status": "skipped",
            "run_id": run_id,
            "reason": "no repeated tool patterns mined",
        }

    # 2. Synthesize + gauntlet each candidate --------------------------------
    from nova_ai.learning.skillforge.gauntlet import run_gauntlet

    max_candidates = int(getattr(config, "max_candidates_per_run", 3))
    auto_adopt = bool(getattr(config, "auto_adopt", False))
    candidates_processed = 0
    forged: list[dict[str, Any]] = []
    attempt = 0

    for pattern in patterns[:max_candidates]:
        attempt += 1
        candidate_run_id = run_id if attempt == 1 else f"{run_id}_{attempt}"
        synthesizer = SkillSynthesizer(llm)
        try:
            manifest = synthesizer.synthesize(pattern)
        except ValueError as exc:
            logger.warning("[skillforge] synthesis failed: %s", exc)
            run_store.finish_run(
                candidate_run_id,
                status="synthesis_failed",
                skill_name="",
                pattern_count=pattern.get("count", 0),
                sequence=pattern.get("sequence", []),
                error=str(exc)[:400],
            )
            continue

        report = run_gauntlet(
            manifest,
            pattern,
            tool_executor=tool_executor,
            config=config,
            judge=judge,
        )
        # Persist the manifest inside the gauntlet report so `nova forge
        # adopt` can reinstall it without another LLM call.
        report["manifest"] = {
            "name": manifest.name,
            "version": manifest.version,
            "description": manifest.description,
            "author": manifest.author,
            "steps": [
                {
                    "tool_name": s.tool_name,
                    "skill_name": s.skill_name,
                    "arguments_template": s.arguments_template,
                    "output_key": s.output_key,
                }
                for s in manifest.steps
            ],
            "required_capabilities": manifest.required_capabilities,
            "tags": manifest.tags,
        }
        candidates_processed += 1
        record_status = "passed" if report["passed"] else "failed"

        adopted = False
        if report["passed"] and auto_adopt:
            from nova_ai.learning.skillforge.adoption import adopt_skill

            try:
                adopt_skill(
                    manifest,
                    run_id=run_id,
                    gauntlet=report,
                    pattern_count=pattern.get("count", 0),
                    skills_root=skills_root,
                )
                adopted = True
                record_status = "adopted"
            except Exception as exc:
                logger.warning("[skillforge] adoption failed: %s", exc)

        run_store.finish_run(
            candidate_run_id,
            status=record_status,
            skill_name=manifest.name,
            pattern_count=pattern.get("count", 0),
            sequence=pattern.get("sequence", []),
            gauntlet=report,
        )
        forged.append(
            {
                "skill_name": manifest.name,
                "status": record_status,
                "adopted": adopted,
                "gauntlet": report,
                "pattern_count": pattern.get("count", 0),
            }
        )

    if not forged:
        return {
            "status": "failed",
            "run_id": run_id,
            "error": "no patterns could be synthesized into skills",
        }

    summary = {
        "patterns_mined": len(patterns),
        "candidates": candidates_processed,
        "passed": sum(1 for f in forged if f["status"] in ("passed", "adopted")),
        "adopted": sum(1 for f in forged if f["adopted"]),
    }
    return {"status": "completed", "run_id": run_id, "skills": forged, **summary}


__all__ = ["default_llm", "run_skillforge", "sanitize_name"]
