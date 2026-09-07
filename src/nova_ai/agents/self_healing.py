"""Self-healing ReAct agent — Plan → Act → Observe → Repair loop.

Extends NOVA AI's native ReAct loop with an explicit error-recovery
phase. When a tool call fails (non-zero exit code, exception, error
marker in output), the failing tool's stderr/error content is fed back
into the conversation inside a dedicated *repair prompt* and the agent
gets up to ``max_repair_iterations`` (default 3) chances to fix its own
approach — adjusting arguments, switching tools, or rewriting code —
before the failure is surfaced as a normal observation.

The loop is agnostic to the tool suite: any registered tool works
(``code_interpreter``, ``shell_exec``, ``file_read``, ``web_search``,
…). Repair behavior is driven by failure classification, not tool ids.

Event flow (all published to the :class:`EventBus` when present):

- ``AGENT_TURN_START`` / ``AGENT_TURN_END`` — per ReAct turn (inherited)
- ``TRACE_STEP`` with ``kind="repair_attempt"`` — each healing iteration
- ``TRACE_STEP`` with ``kind="repair_success"`` — recovery achieved
- ``TRACE_STEP`` with ``kind="repair_exhausted"`` — gave up after N tries

Usage::

    agent = SelfHealingReActAgent(engine, model, tools=[...])
    result = agent.run("Write a python script that parses data.csv")

    # Inspect what happened
    result.metadata["plan"]                 # the initial plan text
    result.metadata["repair_count"]         # e.g. 2
    result.metadata["healed"]               # True if a repair succeeded
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from nova_ai.agents._stubs import AgentContext, AgentResult
from nova_ai.agents.loop_guard import LoopGuard  # noqa: F401  (type re-export)
from nova_ai.agents.native_react import REACT_SYSTEM_PROMPT, NativeReActAgent
from nova_ai.agents.prompt_loader import load_system_prompt_override
from nova_ai.core.events import EventBus, EventType
from nova_ai.core.registry import AgentRegistry
from nova_ai.core.types import Message, Role, ToolCall, ToolResult
from nova_ai.tools._stubs import build_tool_descriptions

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

# Markers that a ToolResult's content describes a failure even when
# ``success`` is (incorrectly) True — some tools embed errors in stdout.
_FAILURE_MARKERS = (
    "traceback (most recent call last)",
    "syntaxerror",
    "indentationerror",
    "nameerror",
    "typeerror",
    "valueerror",
    "zerodivisionerror",
    "filenotfounderror",
    "permissionerror",
    "modulenotfounderror",
    "keyerror",
    "indexerror",
    "attributeerror",
    "runtimeerror",
    "command not found",
    "is not recognized as an internal or external command",
    "no such file or directory",
    "permission denied",
    "exit code 1",
    "exit_code': 1",
    "returncode': 1",
    "=== stderr ===",
)

# Content prefixes a repair prompt should never replay (huge outputs)
_MAX_REPAIR_ERROR_CHARS = 4000


def classify_failure(result: ToolResult) -> Optional[str]:
    """Return a failure category for a ToolResult, or None if it succeeded.

    Categories: ``exit_code``, ``exception``, ``error_output``, ``timeout``.
    """
    if getattr(result, "success", True) is False:
        content = (result.content or "").lower()
        if "timed out" in content or "timeout" in content:
            return "timeout"
        return "exit_code"
    content = (result.content or "").lower()
    if "execution timed out" in content:
        return "timeout"
    for marker in _FAILURE_MARKERS:
        if marker in content:
            return "error_output"
    return None


def _trim_error(content: str, limit: int = _MAX_REPAIR_ERROR_CHARS) -> str:
    """Keep the tail of an error — tracebacks put the exception last."""
    content = content or ""
    if len(content) <= limit:
        return content
    return "…(truncated head)…\n" + content[-limit:]


REPAIR_SYSTEM_PROMPT = """\
You are the self-repair module of a ReAct agent. The last tool call
FAILED. A hidden supervisor has captured the error output.

Your job:
1. Diagnose the root cause from the error output.
2. Retry with a CORRECTED action — fix arguments, fix the code, or
   choose a different tool that accomplishes the same sub-goal.
3. Do NOT repeat the identical failing call.

Respond in the same ReAct format:
Thought: <root-cause analysis>
Action: <tool_name>
Action Input: <json arguments>

If you conclude the sub-goal is impossible after seeing the error:
Thought: <why>
Final Answer: <partial result or explanation>
"""

# Model-agnostic JSON-extraction (models sometimes wrap JSON in prose/fences)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def extract_json(text: str) -> Optional[str]:
    """Pull the first JSON object/array out of model output, if any."""
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        return fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        return text[start : end + 1]
    return None


@AgentRegistry.register("self_healing_react")
class SelfHealingReActAgent(NativeReActAgent):
    """ReAct agent with a Plan phase and a bounded self-repair loop."""

    agent_id = "self_healing_react"
    _default_max_turns = 15
    _default_max_repairs = 3

    def __init__(
        self,
        engine,
        model: str,
        *,
        tools=None,
        bus: Optional[EventBus] = None,
        max_turns: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_repair_iterations: Optional[int] = None,
        plan_first: bool = True,
        interactive: bool = False,
        confirm_callback=None,
        skill_few_shot_examples: Optional[List[str]] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            tools=tools,
            bus=bus,
            max_turns=max_turns,
            temperature=temperature,
            max_tokens=max_tokens,
            interactive=interactive,
            confirm_callback=confirm_callback,
            skill_few_shot_examples=skill_few_shot_examples,
        )
        self._max_repairs = (
            max_repair_iterations
            if max_repair_iterations is not None
            else self._default_max_repairs
        )
        self._plan_first = plan_first
        self._bus = bus

    # -- planning -------------------------------------------------------------

    def _make_plan(self, input: str, context: Optional[AgentContext]) -> Optional[str]:
        """Ask the model for a short plan before entering the ReAct loop.

        Best-effort: any parse or engine error leaves the plan as None and
        the agent behaves like the plain ReAct agent.
        """
        if not self._plan_first:
            return None
        tool_names = ", ".join(
            sorted({t.spec.name for t in self._tools if hasattr(t, "spec")})
        )
        plan_prompt = (
            "Goal: "
            + input
            + "\n\nAvailable tools: "
            + (tool_names or "(none)")
            + "\n\nProduce a numbered step-by-step plan (max 6 steps) to "
            "accomplish this goal using the available tools. "
            "One line per step. Output ONLY the plan."
        )
        try:
            messages = [Message(role=Role.USER, content=plan_prompt)]
            result = self._generate_plan(messages)
            plan_text = (result.get("content") or "").strip()
            return plan_text or None
        except Exception:  # noqa: BLE001 — planning must never break the run
            logger.debug("Plan generation failed; skipping plan phase", exc_info=True)
            return None

    def _generate_plan(self, messages: list) -> dict:
        """Lower-temperature generate for the plan phase.

        Calls the engine directly (bypassing ``_generate``) so the stored
        agent temperature doesn't collide with the plan's.
        """
        return self._engine.generate(
            messages,
            model=self._model,
            temperature=0.3,
            max_tokens=self._max_tokens,
        )

    def _generate_repair(self, messages: list) -> dict:
        """Lower-temperature generate for repair turns (focused correcting)."""
        return self._engine.generate(
            messages,
            model=self._model,
            temperature=0.4,
            max_tokens=self._max_tokens,
        )

    # -- repair loop ------------------------------------------------------------

    def _emit_trace(self, kind: str, **data: Any) -> None:
        if not self._bus:
            return
        try:
            self._bus.publish(EventType.TRACE_STEP, {"kind": kind, **data})
        except Exception:  # noqa: BLE001 — events must never break the run
            logger.debug("Failed to emit %s trace event", kind, exc_info=True)

    def _repair_prompt(self, failure_kind: str, tool_name: str, error_text: str) -> str:
        """Build the hidden repair message replayed after a failure."""
        return (
            f"SYSTEM REPAIR NOTICE\n"
            f"===================\n"
            f"The previous call to tool `{tool_name}` FAILED "
            f"(failure type: {failure_kind}).\n\n"
            f"Error output:\n```\n{_trim_error(error_text)}\n```\n\n"
            f"Attempt {self._repair_attempts_used + 1} of "
            f"{self._max_repairs}: diagnose the error and issue a corrected "
            f"Action. Do not repeat the identical failing call."
        )

    def _run_repairs(
        self,
        messages: List[Message],
        failed_tool: str,
        failure_kind: str,
        error_text: str,
        all_tool_results: List[ToolResult],
        failed_action_content: str = "",
    ) -> bool:
        """Try up to ``max_repairs`` corrective actions for one failure.

        The repair dialogue runs in a hidden sub-loop: repair messages are
        tagged in metadata and only the final corrected observation is
        appended to the main conversation. Returns True if a later call of
        the same tool (or any tool) succeeded, healing the step.

        Mutates ``messages`` in place. ``failed_action_content`` is the
        assistant turn that made the failing call — it is committed
        immediately so the transcript order stays chronological no matter
        how the repair loop ends (append-only from here on).
        """
        # Commit the failing turn up-front, BEFORE any repair turns. The old
        # code left it uncommitted and run() appended the failure
        # observation after the repair sub-loop returned — putting the
        # original error AFTER the attempts that tried to fix it.
        if failed_action_content:
            messages.append(
                Message(role=Role.ASSISTANT, content=failed_action_content)
            )
        messages.append(
            Message(
                role=Role.USER,
                content=f"Observation: {error_text or '[empty error output]'}",
            )
        )

        self._repair_attempts_used = 0

        while self._repair_attempts_used < self._max_repairs:
            self._repair_attempts_used += 1
            repair_text = self._repair_prompt(failure_kind, failed_tool, error_text)
            self._emit_trace(
                "repair_attempt",
                attempt=self._repair_attempts_used,
                tool=failed_tool,
                failure_kind=failure_kind,
            )

            # Hidden repair turn: repair notice + ReAct system reminder
            repair_messages = list(messages)
            repair_messages.append(Message(role=Role.USER, content=repair_text))

            try:
                result = self._generate_repair(repair_messages)
            except Exception as exc:  # noqa: BLE001 — engine hiccup counts as attempt
                logger.warning("Repair generation failed: %s", exc)
                continue

            content = result.get("content", "")
            parsed = self._parse_response(content)

            # Model chose to bail out with a final answer → step is unhealed
            if parsed["final_answer"] and not parsed["action"]:
                messages.extend(
                    [
                        Message(role=Role.ASSISTANT, content=content),
                        Message(
                            role=Role.USER,
                            content=f"Observation: {parsed['final_answer']}",
                        ),
                    ]
                )
                self._emit_trace(
                    "repair_exhausted",
                    attempt=self._repair_attempts_used,
                    tool=failed_tool,
                )
                return False

            if not parsed["action"]:
                # Malformed repair output — count the attempt and retry
                logger.debug("Repair output had no Action; retrying")
                continue

            # Execute the corrected action
            tool_call = ToolCall(
                id=f"repair_{self._repair_attempts_used}",
                name=parsed["action"],
                arguments=parsed["action_input"] or "{}",
            )

            if self._loop_guard:
                verdict = self._loop_guard.check_call(
                    tool_call.name, tool_call.arguments
                )
                if verdict.blocked:
                    error_text = f"Loop guard: {verdict.reason}"
                    failure_kind = "loop_guard"
                    continue

            tool_result = self._executor.execute(tool_call)
            all_tool_results.append(tool_result)

            new_failure = classify_failure(tool_result)
            if new_failure is None:
                # HEALED — append the corrected turn (the failed exchange is
                # already committed above; append-only keeps order sane).
                self._emit_trace(
                    "repair_success",
                    attempt=self._repair_attempts_used,
                    tool=tool_call.name,
                )
                messages.append(Message(role=Role.ASSISTANT, content=content))
                messages.append(
                    Message(
                        role=Role.USER,
                        content=f"Observation: {tool_result.content}",
                    )
                )
                return True

            # Still failing — feed the new error back for the next attempt
            failure_kind = new_failure
            failed_tool = tool_call.name
            error_text = tool_result.content or ""
            messages.append(Message(role=Role.ASSISTANT, content=content))
            messages.append(
                Message(
                    role=Role.USER,
                    content=f"Observation: {tool_result.content}",
                )
            )

        self._emit_trace(
            "repair_exhausted", attempt=self._max_repairs, tool=failed_tool
        )
        return False

    # -- main loop ---------------------------------------------------------------

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Run with Plan → ReAct → Self-Repair semantics.

        Overrides :meth:`NativeReActAgent.run` — same ReAct skeleton, with:
        - an upfront plan (stored in metadata, injected into the prompt)
        - failure classification after every tool execution
        - the bounded repair sub-loop on failure
        """
        self._emit_turn_start(input)

        # Build system prompt (same construction as the native agent)
        tool_desc = build_tool_descriptions(self._tools)
        if self._skill_few_shot_examples:
            skill_examples_block = (
                "## Skill Examples\n\n"
                + "\n\n".join(self._skill_few_shot_examples)
                + "\n\n"
            )
        else:
            skill_examples_block = ""
        prompt_template = (
            load_system_prompt_override("self_healing_react") or REACT_SYSTEM_PROMPT
        )
        try:
            system_prompt = prompt_template.format(
                tool_descriptions=tool_desc,
                skill_examples=skill_examples_block,
            )
        except KeyError:
            system_prompt = prompt_template.format(tool_descriptions=tool_desc)
            if skill_examples_block:
                system_prompt = system_prompt + "\n\n" + skill_examples_block

        messages = self._build_messages(input, context, system_prompt=system_prompt)

        # ---- Plan phase ----
        plan = self._make_plan(input, context)
        if plan:
            messages.append(
                Message(
                    role=Role.USER,
                    content=(
                        f"Your approved plan:\n{plan}\n\n"
                        "Now execute step 1. Follow ReAct format."
                    ),
                )
            )

        all_tool_results: List[ToolResult] = []
        turns = 0
        repair_count = 0
        healed_any = False
        total_usage: Dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        for _turn in range(self._max_turns):
            turns += 1

            if self._loop_guard:
                messages = self._loop_guard.compress_context(messages)

            result = self._generate(messages)
            usage = result.get("usage", {})
            for k in total_usage:
                total_usage[k] += usage.get(k, 0)

            content = result.get("content", "")
            parsed = self._parse_response(content)

            if parsed["final_answer"]:
                self._emit_turn_end(turns=turns)
                return self._result(
                    parsed["final_answer"],
                    messages,
                    all_tool_results,
                    turns,
                    total_usage,
                    plan,
                    repair_count,
                    healed_any,
                )

            if not parsed["action"]:
                self._emit_turn_end(turns=turns)
                return self._result(
                    content,
                    messages,
                    all_tool_results,
                    turns,
                    total_usage,
                    plan,
                    repair_count,
                    healed_any,
                )

            # The failing turn's assistant message is committed inside
            # _run_repairs (it must land before the failure observation);
            # only append it here when the tool did NOT fail.
            tool_call = ToolCall(
                id=f"react_{turns}",
                name=parsed["action"],
                arguments=parsed["action_input"] or "{}",
            )

            if self._loop_guard:
                verdict = self._loop_guard.check_call(
                    tool_call.name, tool_call.arguments
                )
                if verdict.blocked:
                    tool_result = ToolResult(
                        tool_name=tool_call.name,
                        content=f"Loop guard: {verdict.reason}",
                        success=False,
                    )
                    all_tool_results.append(tool_result)
                    messages.append(
                        Message(role=Role.ASSISTANT, content=content)
                    )
                    messages.append(
                        Message(
                            role=Role.USER,
                            content=f"Observation: {tool_result.content}",
                        )
                    )
                    continue

            tool_result = self._executor.execute(tool_call)
            all_tool_results.append(tool_result)

            failure_kind = classify_failure(tool_result)
            if failure_kind is not None:
                # ---- Self-healing sub-loop ----
                self._repair_attempts_used = 0
                healed = self._run_repairs(
                    messages,
                    tool_call.name,
                    failure_kind,
                    tool_result.content or "",
                    all_tool_results,
                    failed_action_content=content,
                )
                repair_count += self._repair_attempts_used
                healed_any = healed or healed_any
                if healed:
                    # _run_repairs committed the failed exchange and the
                    # healed turn already.
                    continue
                # The failed exchange was committed inside _run_repairs;
                # just mark the exhaustion on the transcript.
                messages.append(
                    Message(
                        role=Role.USER,
                        content=(
                            f"[repair exhausted after {self._max_repairs} attempts]"
                        ),
                    )
                )
                continue

            messages.append(Message(role=Role.ASSISTANT, content=content))
            messages.append(
                Message(role=Role.USER, content=f"Observation: {tool_result.content}")
            )

        max_result = self._max_turns_result(all_tool_results, turns)
        return self._result(
            max_result.content or "",
            messages,
            all_tool_results,
            turns,
            total_usage,
            plan,
            repair_count,
            healed_any,
        )

    def _result(
        self,
        content: str,
        messages: List[Message],
        tool_results: List[ToolResult],
        turns: int,
        usage: Dict[str, int],
        plan: Optional[str],
        repair_count: int,
        healed: bool,
    ) -> AgentResult:
        return AgentResult(
            content=content,
            tool_results=tool_results,
            turns=turns,
            metadata={
                **usage,
                "messages": [
                    {
                        "role": getattr(m.role, "value", str(m.role)),
                        "content": m.content,
                    }
                    for m in messages
                ],
                "plan": plan,
                "repair_count": repair_count,
                "healed": healed,
            },
        )


__all__ = [
    "SelfHealingReActAgent",
    "REPAIR_SYSTEM_PROMPT",
    "classify_failure",
    "extract_json",
]
