"""Tests for the self-healing ReAct agent loop."""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from nova_ai.agents.self_healing import (
    SelfHealingReActAgent,
    classify_failure,
    extract_json,
)
from nova_ai.core.events import EventBus, EventType
from nova_ai.core.types import ToolResult

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeEngine:
    """Scripted engine: pops pre-baked responses for each generate call."""

    engine_id = "fake"

    def __init__(self, responses: List[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def generate(self, messages, model=None, **kwargs) -> Dict[str, Any]:
        self.calls += 1
        if not self.responses:
            return {"content": "Final Answer: exhausted", "usage": {}}
        return {"content": self.responses.pop(0), "usage": {"total_tokens": 1}}


class FlakyTool:
    """Fails N times, then succeeds. Records every call."""

    def __init__(self, fail_times: int = 1) -> None:
        self.fail_times = fail_times
        self.calls: List[Dict[str, Any]] = []

    @property
    def spec(self):
        from nova_ai.tools._stubs import ToolSpec

        return ToolSpec(
            name="flaky",
            description="Flaky test tool.",
            parameters={"type": "object", "properties": {"code": {"type": "string"}}},
        )

    def execute(self, **params: Any) -> ToolResult:
        self.calls.append(params)
        if len(self.calls) <= self.fail_times:
            return ToolResult(
                tool_name="flaky",
                content="Traceback (most recent call last):\n  ZeroDivisionError: division by zero",
                success=False,
            )
        return ToolResult(tool_name="flaky", content="42", success=True)


# ---------------------------------------------------------------------------
# Unit: failure classification / JSON extraction
# ---------------------------------------------------------------------------


def test_classify_failure_categories() -> None:
    ok = ToolResult(tool_name="x", content="fine", success=True)
    assert classify_failure(ok) is None

    err = ToolResult(tool_name="x", content="boom", success=False)
    assert classify_failure(err) == "exit_code"

    sneaky = ToolResult(
        tool_name="x", content="NameError: foo not defined", success=True
    )
    assert classify_failure(sneaky) == "error_output"

    timeout = ToolResult(
        tool_name="x", content="Execution timed out after 30 seconds.", success=True
    )
    assert classify_failure(timeout) == "timeout"

    stderr = ToolResult(
        tool_name="x", content="=== STDERR ===\ncmd failed", success=True
    )
    assert classify_failure(stderr) == "error_output"


def test_extract_json_variants() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json('text {"b": 2} tail') == '{"b": 2}'
    assert extract_json("none here") is None


# ---------------------------------------------------------------------------
# Integration: repair loop heals a failing tool call
# ---------------------------------------------------------------------------


def _react(thought: str, action: str, action_input: dict) -> str:
    return (
        f"Thought: {thought}\nAction: {action}\n"
        f"Action Input: {json.dumps(action_input)}"
    )


def test_repair_loop_heals_failing_tool() -> None:
    flaky = FlakyTool(fail_times=1)
    engine = FakeEngine(
        [
            "1. Run the flaky tool",  # plan
            _react("start", "flaky", {"code": "1/0"}),  # fails
            _react("fix: divide by nonzero", "flaky", {"code": "4/2"}),  # heals
            "Final Answer: the answer is 42",  # wrap up
        ]
    )
    agent = SelfHealingReActAgent(
        engine, "fake-model", tools=[flaky], plan_first=True
    )
    result = agent.run("compute something")

    assert result.metadata["healed"] is True
    assert result.metadata["repair_count"] == 1
    assert result.metadata["plan"] is not None
    assert len(flaky.calls) == 2
    assert result.content == "the answer is 42"


def test_repair_loop_exhausts_after_max_attempts() -> None:
    flaky = FlakyTool(fail_times=10)  # never succeeds
    engine = FakeEngine(
        [
            "1. Run the flaky tool",  # plan
            _react("start", "flaky", {"code": "1/0"}),  # fails
            _react("retry1", "flaky", {"code": "2/0"}),  # fails
            _react("retry2", "flaky", {"code": "3/0"}),  # fails
            _react("retry3", "flaky", {"code": "4/0"}),  # fails
            "Final Answer: gave up",  # after exhaustion
        ]
    )
    agent = SelfHealingReActAgent(
        engine, "fake-model", tools=[flaky], plan_first=True
    )
    result = agent.run("compute something")

    assert result.metadata["healed"] is False
    # 1 initial + 3 repair attempts
    assert result.metadata["repair_count"] == 3
    assert len(flaky.calls) == 4
    assert "repair exhausted" in "".join(
        m["content"] for m in result.metadata["messages"]
    )


def test_no_repair_when_tool_succeeds() -> None:
    flaky = FlakyTool(fail_times=0)
    engine = FakeEngine(
        [
            "1. Run it",  # plan
            _react("start", "flaky", {"code": "ok"}),
            "Final Answer: done",
        ]
    )
    agent = SelfHealingReActAgent(engine, "fake-model", tools=[flaky])
    result = agent.run("compute something")

    assert result.metadata["repair_count"] == 0
    assert result.metadata["healed"] is False
    assert len(flaky.calls) == 1


def test_plan_first_disabled_skips_plan() -> None:
    flaky = FlakyTool(fail_times=0)
    engine = FakeEngine(
        [
            _react("start", "flaky", {"code": "ok"}),
            "Final Answer: done",
        ]
    )
    agent = SelfHealingReActAgent(
        engine, "fake-model", tools=[flaky], plan_first=False
    )
    result = agent.run("compute something")
    assert result.metadata["plan"] is None
    # No extra plan-generation call: engine saw exactly 2 generate calls
    assert engine.calls == 2


def test_repair_traces_published() -> None:
    events: List[Any] = []
    bus = EventBus(record_history=False)
    bus.subscribe(EventType.TRACE_STEP, lambda e: events.append(e))

    flaky = FlakyTool(fail_times=1)
    engine = FakeEngine(
        [
            "1. Run it",  # plan
            _react("start", "flaky", {"code": "1/0"}),
            _react("fix", "flaky", {"code": "4/2"}),
            "Final Answer: done",
        ]
    )
    agent = SelfHealingReActAgent(
        engine, "fake-model", tools=[flaky], bus=bus
    )
    agent.run("compute something")

    kinds = [e.data.get("kind") for e in events]
    assert "repair_attempt" in kinds
    assert "repair_success" in kinds


def test_repair_success_message_history_is_clean() -> None:
    """After healing, the transcript should show thought -> healed observation,
    not the raw failure (the failed exchange is replaced)."""
    flaky = FlakyTool(fail_times=1)
    engine = FakeEngine(
        [
            _react("start", "flaky", {"code": "1/0"}),
            _react("fix", "flaky", {"code": "4/2"}),
            "Final Answer: done",
        ]
    )
    agent = SelfHealingReActAgent(
        engine, "fake-model", tools=[flaky], plan_first=False
    )
    result = agent.run("compute something")
    user_msgs = [
        m["content"]
        for m in result.metadata["messages"]
        if m["role"] == "user"
    ]
    # The healed observation is present…
    assert any("42" in c for c in user_msgs)
    # …and the last Observation is the success, not the traceback
    observations = [c for c in user_msgs if c.startswith("Observation:")]
    assert observations and "Traceback" not in observations[-1]


@pytest.mark.parametrize("fail_times", [1, 2])
def test_multi_failure_then_success(fail_times: int) -> None:
    flaky = FlakyTool(fail_times=fail_times)
    engine = FakeEngine(
        [_react("start", "flaky", {"code": "x"})]
        + [
            _react(f"fix{i}", "flaky", {"code": f"y{i}"})
            for i in range(fail_times)
        ]
        + ["Final Answer: recovered"]
    )
    agent = SelfHealingReActAgent(
        engine, "fake-model", tools=[flaky], plan_first=False
    )
    result = agent.run("go")
    assert result.metadata["healed"] is True
    assert result.metadata["repair_count"] == fail_times
