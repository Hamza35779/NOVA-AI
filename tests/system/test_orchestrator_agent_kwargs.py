"""Tests for QueryOrchestrator agent construction.

Regression coverage: when a composed recipe's agent_kwargs contained a
parameter the agent's ``__init__`` did not accept (historically
``system_prompt``), the TypeError fallback re-instantiated a *bare* agent,
silently discarding tools and the system prompt.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from nova_ai.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from nova_ai.core.events import EventBus
from nova_ai.core.registry import AgentRegistry
from nova_ai.core.types import Message, Role, ToolResult
from nova_ai.system.orchestrator import QueryOrchestrator
from nova_ai.tools._stubs import BaseTool, ToolSpec


class _StubTool(BaseTool):
    tool_id = "stub"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="stub",
            description="A stub tool.",
            parameters={"type": "object", "properties": {}},
        )

    def execute(self, **params: Any) -> ToolResult:
        return ToolResult(tool_name="stub", content="ok", success=True)


class _RestrictedAgent(ToolUsingAgent):
    """Mimics agents whose __init__ predates the ``system_prompt`` kwarg."""

    agent_id = "restricted_test"

    captured: Dict[str, Any] = {}

    def __init__(
        self,
        engine: Any,
        model: str,
        *,
        tools: Optional[List[Any]] = None,
        bus: Any = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_turns: Optional[int] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            tools=tools,
            bus=bus,
            temperature=temperature,
            max_tokens=max_tokens,
            max_turns=max_turns,
        )
        _RestrictedAgent.captured = {"tools": tools}

    def run(
        self, input: str, context: Optional[AgentContext] = None, **kwargs: Any
    ) -> AgentResult:
        return AgentResult(content="ok", turns=1)


class _PromptAgent(ToolUsingAgent):
    """Accepts ``system_prompt`` (like the fixed ``native_react``)."""

    agent_id = "prompt_test"

    captured: Dict[str, Any] = {}

    def __init__(
        self,
        engine: Any,
        model: str,
        *,
        tools: Optional[List[Any]] = None,
        bus: Any = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_turns: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            tools=tools,
            bus=bus,
            temperature=temperature,
            max_tokens=max_tokens,
            max_turns=max_turns,
            system_prompt=system_prompt,
        )
        _PromptAgent.captured = {"tools": tools, "system_prompt": system_prompt}

    def run(
        self, input: str, context: Optional[AgentContext] = None, **kwargs: Any
    ) -> AgentResult:
        return AgentResult(content="ok", turns=1)


@pytest.fixture()
def orch() -> QueryOrchestrator:
    s = MagicMock()
    s.tools = [_StubTool()]
    s.engine = MagicMock()
    s.engine.engine_id = "mock"
    s.model = "test-model"
    s.bus = EventBus(record_history=False)
    s.capability_policy = None
    s.trace_store = None
    s.config.agent.max_turns = 5
    return QueryOrchestrator(s)


def _run(orch: QueryOrchestrator, agent_name: str) -> Dict[str, Any]:
    return orch._run_agent(
        "do the thing",
        [Message(role=Role.USER, content="do the thing")],
        agent_name,
        None,
        0.3,
        100,
        system_prompt="CUSTOM RECIPE PROMPT",
    )


def test_restricted_agent_keeps_tools(orch: QueryOrchestrator) -> None:
    """TypeError fallback must keep tools, not rebuild a bare agent."""
    AgentRegistry.register_value("restricted_test", _RestrictedAgent)
    _run(orch, "restricted_test")
    assert _RestrictedAgent.captured["tools"], "tools were silently dropped"
    assert _RestrictedAgent.captured["tools"][0].spec.name == "stub"


def test_prompt_agent_receives_prompt_and_tools(orch: QueryOrchestrator) -> None:
    AgentRegistry.register_value("prompt_test", _PromptAgent)
    _run(orch, "prompt_test")
    assert _PromptAgent.captured["tools"]
    assert _PromptAgent.captured["system_prompt"] == "CUSTOM RECIPE PROMPT"
