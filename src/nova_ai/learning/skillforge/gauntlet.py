"""The forge gauntlet — a candidate skill must pass every gate to survive.

Sequential gates, each reported by name:

1. ``static``  — name/description sanity, capability validation
   (:func:`skills.security.validate_capabilities`,
   :func:`~skills.security.has_dangerous_capabilities`), and every step
   must target a tool that actually exists in the ToolRegistry.
2. ``replay``  — for each mined example, run the manifest through
   ``SkillExecutor`` against the injected tool executor. Code-interpreter
   -class tools are forced through the subprocess sandbox
   (:func:`security.subprocess_sandbox.run_sandboxed`) with the
   configured ``sandbox_timeout``.
3. ``judge``   — the LLM compares replay outputs with the trace's
   known-good result (first line YES/NO, same convention as
   ``PersonalBenchmarkScorer``).

Any gate failure short-circuits; the report records every gate's outcome.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from nova_ai.skills.security import (
    has_dangerous_capabilities,
    validate_capabilities,
)
from nova_ai.skills.types import SkillManifest

logger = logging.getLogger(__name__)

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024

# Tools whose execution must go through the subprocess sandbox during
# replay (code/shell-shaped tools).
_SANDBOXED_TOOLS = frozenset(
    {"code_interpreter", "shell", "bash", "terminal", "python_repl"}
)


def _tool_catalog_names() -> set[str]:
    from nova_ai.core.registry import ToolRegistry

    try:
        names = set(ToolRegistry.keys())
        if names:
            return names
    except Exception:
        pass
    # Registries are lazily populated; force tool-module import so the
    # static gate sees the full catalog even in a bare interpreter.
    try:
        import nova_ai.tools  # noqa: F401

        return set(ToolRegistry.keys())
    except Exception:
        return set()


def _static_gate(manifest: SkillManifest) -> dict[str, Any]:
    problems: list[str] = []
    name = manifest.name or ""
    if not name or len(name) > MAX_NAME_LENGTH:
        problems.append(f"name must be 1-{MAX_NAME_LENGTH} chars")
    if not (manifest.description or "").strip():
        problems.append("description must not be empty")
    if len(manifest.description or "") > MAX_DESCRIPTION_LENGTH:
        problems.append(f"description exceeds {MAX_DESCRIPTION_LENGTH} chars")
    if not manifest.steps:
        problems.append("manifest has no steps")
    if has_dangerous_capabilities(manifest):
        problems.append(
            f"dangerous capabilities required: "
            f"{has_dangerous_capabilities(manifest)}"
        )
    unknown = validate_capabilities(manifest, allowed=set())
    if unknown:
        problems.append(f"capabilities not authorized: {unknown}")

    catalog = _tool_catalog_names()
    if catalog:
        for step in manifest.steps:
            target = step.tool_name or step.skill_name
            if not target:
                problems.append("step with no tool_name or skill_name")
            elif step.tool_name and step.tool_name not in catalog:
                problems.append(f"unknown tool {step.tool_name!r}")

    return {
        "name": "static",
        "passed": not problems,
        "detail": "; ".join(problems) if problems else "all checks passed",
    }


class _SandboxedExecutor:
    """ToolExecutor wrapper forcing code/shell tools through the sandbox."""

    def __init__(self, inner: Any, timeout: float) -> None:
        self._inner = inner
        self._timeout = timeout

    def execute(self, tool_call: Any) -> Any:
        from nova_ai.core.types import ToolResult
        from nova_ai.security.subprocess_sandbox import run_sandboxed

        if tool_call.name not in _SANDBOXED_TOOLS:
            return self._inner.execute(tool_call)

        # The call's arguments are a JSON object; run its "command"/"code"
        # payload through run_sandboxed. Refuse anything unshellable.
        try:
            params = json.loads(tool_call.arguments) if isinstance(
                tool_call.arguments, str
            ) else dict(tool_call.arguments)
        except (json.JSONDecodeError, TypeError):
            params = {}
        command = params.get("command") or params.get("code") or ""
        if not isinstance(command, str) or not command.strip():
            return ToolResult(
                tool_name=tool_call.name,
                content="sandbox: no shell-runnable command in arguments",
                success=False,
            )
        result = run_sandboxed(command, timeout=self._timeout)
        return ToolResult(
            tool_name=tool_call.name,
            content=result.stdout or result.stderr,
            success=(result.returncode == 0 and not result.timed_out),
        )


def _replay_gate(
    manifest: SkillManifest,
    candidate: dict[str, Any],
    *,
    tool_executor: Any,
    sandbox_timeout: float,
) -> dict[str, Any]:
    from nova_ai.skills.executor import SkillExecutor

    problems: list[str] = []
    replayed = 0
    executor = SkillExecutor(_SandboxedExecutor(tool_executor, sandbox_timeout))
    for example in candidate.get("examples", [])[:3]:
        initial = {"query": example.get("query", "")}
        args = example.get("arguments")
        if isinstance(args, dict) and args:
            initial.update({k: str(v) for k, v in args.items()})
        try:
            result = executor.run(manifest, initial_context=initial)
        except Exception as exc:
            problems.append(f"replay raised: {exc}")
            continue
        replayed += 1
        if not result.success:
            failed = [
                r.tool_name for r in result.step_results if not r.success
            ]
            problems.append(
                f"replay failed at {failed or 'unknown step'}: "
                f"{(result.step_results[-1].content if result.step_results else '')[:120]}"
            )
    detail = (
        f"{replayed} example(s) replayed; " + "; ".join(problems)
        if problems
        else f"{replayed} example(s) replayed successfully"
    )
    return {"name": "replay", "passed": not problems, "detail": detail}


def _judge_gate(
    manifest: SkillManifest,
    candidate: dict[str, Any],
    *,
    judge: Any,
    replay_outputs: Optional[list[str]] = None,
) -> dict[str, Any]:
    """LLM compares replay outputs with the known-good trace result."""
    if judge is None:
        return {"name": "judge", "passed": True, "detail": "no judge configured; skipped"}

    known_good = "\n".join(
        (ex.get("query") or "") for ex in candidate.get("examples", [])[:1]
    )
    outputs = "\n".join(replay_outputs or [])
    prompt = (
        "A skill was synthesized to automate a repeated workflow.\n\n"
        f"Skill: {manifest.name} — {manifest.description}\n\n"
        f"Example task: {known_good[:400]}\n\n"
        f"Skill output on that task:\n{outputs[:1200]}\n\n"
        "Does this output plausibly accomplish the task? Respond with exactly "
        '"YES" or "NO" on the first line, then explain.'
    )
    try:
        response = judge.generate(prompt)
    except Exception as exc:
        return {"name": "judge", "passed": False, "detail": f"judge call failed: {exc}"}
    first_line = (response or "").strip().split("\n")[0].strip().upper()
    passed = first_line.startswith("YES")
    return {
        "name": "judge",
        "passed": passed,
        "detail": (response or "")[:200],
    }


def run_gauntlet(
    manifest: SkillManifest,
    candidate: dict[str, Any],
    *,
    tool_executor: Any,
    config: Any,
    judge: Any = None,
) -> dict[str, Any]:
    """Run all gates sequentially; return ``{passed, gates: [...]}``."""
    from nova_ai.skills.executor import SkillExecutor

    gates: list[dict[str, Any]] = []

    static = _static_gate(manifest)
    gates.append(static)
    if not static["passed"]:
        return {"passed": False, "gates": gates}

    replay = _replay_gate(
        manifest,
        candidate,
        tool_executor=tool_executor,
        sandbox_timeout=float(getattr(config, "sandbox_timeout", 30.0)),
    )
    gates.append(replay)

    if replay["passed"] and judge is not None:
        # Re-run once silently to capture outputs for the judge.
        executor = SkillExecutor(
            _SandboxedExecutor(tool_executor, float(getattr(config, "sandbox_timeout", 30.0)))
        )
        outputs: list[str] = []
        for example in candidate.get("examples", [])[:1]:
            initial = {"query": example.get("query", "")}
            args = example.get("arguments")
            if isinstance(args, dict) and args:
                initial.update({k: str(v) for k, v in args.items()})
            try:
                res = executor.run(manifest, initial_context=initial)
                outputs.append(
                    " ".join(r.content for r in res.step_results if r.success)
                )
            except Exception:
                continue
        judge_gate = _judge_gate(
            manifest, candidate, judge=judge, replay_outputs=outputs
        )
        gates.append(judge_gate)

    return {"passed": all(g["passed"] for g in gates), "gates": gates}


__all__ = ["run_gauntlet"]
