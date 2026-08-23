"""Tests for the Operators subsystem."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from nova_ai.operators.types import OperatorManifest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeEngine:
    """Minimal engine stub for tests."""

    def __init__(self, responses: Optional[List[Dict[str, Any]]] = None) -> None:
        self._responses = list(responses or [{"content": "Done."}])
        self._call_idx = 0
        self.calls: List[Any] = []

    def generate(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if self._call_idx < len(self._responses):
            resp = self._responses[self._call_idx]
            self._call_idx += 1
            return resp
        return {"content": "Fallback."}

    def list_models(self):
        return ["test-model"]

    def health(self):
        return True


class FakeSessionStore:
    """Minimal session store stub."""

    def __init__(self) -> None:
        self._sessions: Dict[str, Any] = {}
        self._messages: Dict[str, List[Dict]] = {}

    def get_or_create(self, session_id: str):
        if session_id not in self._sessions:
            self._sessions[session_id] = MagicMock(messages=[])
        return self._sessions[session_id]

    def save_message(self, session_id: str, message: Dict) -> None:
        self._messages.setdefault(session_id, []).append(message)


class FakeMemoryBackend:
    """Minimal memory backend stub."""

    def __init__(self) -> None:
        self._store: Dict[str, str] = {}

    def store(self, key: str, value: str, **kwargs) -> None:
        self._store[key] = value

    def retrieve(self, key: str, **kwargs) -> str:
        return self._store.get(key, "")

    def search(self, query: str, **kwargs):
        return []


class FakeSchedulerStore:
    """Minimal scheduler store stub."""

    def __init__(self) -> None:
        self._tasks: Dict[str, Dict] = {}
        self._runs: List[Dict] = []

    def save_task(self, task_dict: Dict) -> None:
        self._tasks[task_dict["id"]] = task_dict

    def get_task(self, task_id: str) -> Optional[Dict]:
        return self._tasks.get(task_id)

    def update_task(self, task_dict: Dict) -> None:
        self._tasks[task_dict["id"]] = task_dict

    def list_tasks(self, *, status=None) -> List[Dict]:
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        return tasks

    def get_due_tasks(self, now: str) -> List[Dict]:
        return []

    def log_run(self, **kwargs) -> None:
        self._runs.append(kwargs)

    def get_run_logs(self, task_id: str, limit: int = 10) -> List[Dict]:
        """Mirror SchedulerStore.get_run_logs (newest first)."""
        runs = [r for r in self._runs if r.get("task_id") == task_id]
        return list(reversed(runs))[:limit]

    def get_runs(self, task_id: str, limit: int = 10) -> List[Dict]:
        return [r for r in self._runs if r.get("task_id") == task_id][:limit]


def _make_system(
    engine=None,
    scheduler=None,
    session_store=None,
    memory_backend=None,
):
    """Build a minimal mock NovaSystem."""
    from nova_ai.core.config import NovaConfig
    from nova_ai.core.events import EventBus

    system = MagicMock()
    system.config = NovaConfig()
    system.bus = EventBus()
    system.engine = engine or FakeEngine()
    system.engine_key = "test"
    system.model = "test-model"
    system.tools = []
    system.scheduler = scheduler
    system.session_store = session_store
    system.memory_backend = memory_backend
    system.operator_manager = None
    return system


# ---------------------------------------------------------------------------
# TestOperatorManifest
# ---------------------------------------------------------------------------


class TestOperatorManifest:
    def test_fields(self):
        m = OperatorManifest(
            id="test",
            name="Test Op",
            version="2.0.0",
            description="A test",
            tools=["think"],
            schedule_type="cron",
            schedule_value="0 9 * * *",
        )
        assert m.id == "test"
        assert m.name == "Test Op"
        assert m.version == "2.0.0"
        assert m.tools == ["think"]
        assert m.schedule_type == "cron"
        assert m.schedule_value == "0 9 * * *"

    def test_defaults(self):
        m = OperatorManifest(id="x", name="X")
        assert m.version == "0.1.0"
        assert m.temperature == 0.3
        assert m.max_turns == 20
        assert m.schedule_type == "interval"
        assert m.schedule_value == "300"
        assert m.tools == []
        assert m.metrics == []
        assert m.settings == {}
        assert m.metadata == {}


# ---------------------------------------------------------------------------
# TestOperatorLoader
# ---------------------------------------------------------------------------


class TestOperatorLoader:
    def test_load_from_toml(self, tmp_path):
        from nova_ai.operators.loader import load_operator

        toml_content = """\
[operator]
id = "my_op"
name = "My Operator"
version = "1.2.0"
description = "Test operator"
author = "test"

[operator.schedule]
type = "interval"
value = "600"

[operator.agent]
tools = ["think", "web_search"]
max_turns = 15
temperature = 0.5
system_prompt = "You are a test operator."
"""
        p = tmp_path / "my_op.toml"
        p.write_text(toml_content)

        m = load_operator(p)
        assert m.id == "my_op"
        assert m.name == "My Operator"
        assert m.version == "1.2.0"
        assert m.tools == ["think", "web_search"]
        assert m.schedule_type == "interval"
        assert m.schedule_value == "600"
        assert m.temperature == 0.5
        assert m.max_turns == 15
        assert m.system_prompt == "You are a test operator."

    def test_inline_prompt(self, tmp_path):
        from nova_ai.operators.loader import load_operator

        toml_content = """\
[operator]
id = "inline"
name = "Inline"

[operator.agent]
system_prompt = "Do things."
"""
        p = tmp_path / "inline.toml"
        p.write_text(toml_content)

        m = load_operator(p)
        assert m.system_prompt == "Do things."

    def test_external_prompt_file(self, tmp_path):
        from nova_ai.operators.loader import load_operator

        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("External prompt content.")

        toml_content = """\
[operator]
id = "external"
name = "External"

[operator.agent]
system_prompt_path = "prompt.md"
"""
        p = tmp_path / "external.toml"
        p.write_text(toml_content)

        m = load_operator(p)
        assert m.system_prompt == "External prompt content."

    def test_missing_file_returns_empty_prompt(self, tmp_path):
        from nova_ai.operators.loader import load_operator

        toml_content = """\
[operator]
id = "missing"
name = "Missing"

[operator.agent]
system_prompt_path = "nonexistent.md"
"""
        p = tmp_path / "missing.toml"
        p.write_text(toml_content)

        m = load_operator(p)
        assert m.system_prompt == ""

    def test_stem_as_default_id(self, tmp_path):
        from nova_ai.operators.loader import load_operator

        toml_content = """\
[operator]
name = "NoID"
"""
        p = tmp_path / "my_operator.toml"
        p.write_text(toml_content)

        m = load_operator(p)
        assert m.id == "my_operator"


# ---------------------------------------------------------------------------
# TestOperatorManager
# ---------------------------------------------------------------------------


class TestOperatorManager:
    def test_register(self):
        from nova_ai.operators.manager import OperatorManager

        system = _make_system()
        mgr = OperatorManager(system)

        m = OperatorManifest(id="test", name="Test")
        mgr.register(m)
        assert mgr.get_manifest("test") is m

    def test_discover(self, tmp_path):
        from nova_ai.operators.manager import OperatorManager

        toml_content = """\
[operator]
id = "discovered"
name = "Discovered"
"""
        (tmp_path / "discovered.toml").write_text(toml_content)

        system = _make_system()
        mgr = OperatorManager(system)
        found = mgr.discover(tmp_path)
        assert len(found) == 1
        assert found[0].id == "discovered"
        assert mgr.get_manifest("discovered") is not None

    def test_activate_creates_scheduler_task(self):
        from nova_ai.operators.manager import OperatorManager
        from nova_ai.scheduler.scheduler import TaskScheduler

        store = FakeSchedulerStore()
        scheduler = TaskScheduler(store)
        system = _make_system(scheduler=scheduler)
        mgr = OperatorManager(system)

        m = OperatorManifest(
            id="test_op",
            name="Test",
            tools=["think"],
            schedule_type="interval",
            schedule_value="60",
        )
        mgr.register(m)
        task_id = mgr.activate("test_op")

        assert task_id == "operator:test_op"
        # Check the task was persisted with deterministic ID
        task_dict = store.get_task("operator:test_op")
        assert task_dict is not None
        assert task_dict["agent"] == "operative"

    def test_activate_uses_operative_agent(self):
        from nova_ai.operators.manager import OperatorManager
        from nova_ai.scheduler.scheduler import TaskScheduler

        store = FakeSchedulerStore()
        scheduler = TaskScheduler(store)
        system = _make_system(scheduler=scheduler)
        mgr = OperatorManager(system)

        m = OperatorManifest(id="ag_test", name="Agent Test")
        mgr.register(m)
        mgr.activate("ag_test")

        task_dict = store.get_task("operator:ag_test")
        assert task_dict["agent"] == "operative"

    def test_activate_passes_metadata(self):
        from nova_ai.operators.manager import OperatorManager
        from nova_ai.scheduler.scheduler import TaskScheduler

        store = FakeSchedulerStore()
        scheduler = TaskScheduler(store)
        system = _make_system(scheduler=scheduler)
        mgr = OperatorManager(system)

        m = OperatorManifest(
            id="meta_test",
            name="Meta",
            system_prompt="Do stuff",
            temperature=0.5,
        )
        mgr.register(m)
        mgr.activate("meta_test")

        task_dict = store.get_task("operator:meta_test")
        meta = task_dict.get("metadata", {})
        assert meta["operator_id"] == "meta_test"
        assert meta["system_prompt"] == "Do stuff"
        assert meta["temperature"] == 0.5

    def test_deactivate(self):
        from nova_ai.operators.manager import OperatorManager
        from nova_ai.scheduler.scheduler import TaskScheduler

        store = FakeSchedulerStore()
        scheduler = TaskScheduler(store)
        system = _make_system(scheduler=scheduler)
        mgr = OperatorManager(system)

        m = OperatorManifest(id="deact", name="Deact")
        mgr.register(m)
        mgr.activate("deact")
        mgr.deactivate("deact")

        task_dict = store.get_task("operator:deact")
        assert task_dict["status"] == "cancelled"

    def test_pause_resume(self):
        from nova_ai.operators.manager import OperatorManager
        from nova_ai.scheduler.scheduler import TaskScheduler

        store = FakeSchedulerStore()
        scheduler = TaskScheduler(store)
        system = _make_system(scheduler=scheduler)
        mgr = OperatorManager(system)

        m = OperatorManifest(id="pr_test", name="PR")
        mgr.register(m)
        mgr.activate("pr_test")

        mgr.pause("pr_test")
        task_dict = store.get_task("operator:pr_test")
        assert task_dict["status"] == "paused"

        mgr.resume("pr_test")
        task_dict = store.get_task("operator:pr_test")
        assert task_dict["status"] == "active"

    def test_status(self):
        from nova_ai.operators.manager import OperatorManager

        system = _make_system()
        mgr = OperatorManager(system)

        m = OperatorManifest(id="s1", name="S1", description="Status test")
        mgr.register(m)

        statuses = mgr.status()
        assert len(statuses) == 1
        assert statuses[0]["id"] == "s1"
        assert statuses[0]["name"] == "S1"
        assert statuses[0]["status"] == "registered"

    def test_activate_idempotent(self):
        from nova_ai.operators.manager import OperatorManager
        from nova_ai.scheduler.scheduler import TaskScheduler

        store = FakeSchedulerStore()
        scheduler = TaskScheduler(store)
        system = _make_system(scheduler=scheduler)
        mgr = OperatorManager(system)

        m = OperatorManifest(id="idem", name="Idem")
        mgr.register(m)
        id1 = mgr.activate("idem")
        id2 = mgr.activate("idem")
        assert id1 == id2

    def test_activate_without_scheduler_raises(self):
        from nova_ai.operators.manager import OperatorManager

        system = _make_system(scheduler=None)
        mgr = OperatorManager(system)

        m = OperatorManifest(id="no_sched", name="No Sched")
        mgr.register(m)

        with pytest.raises(RuntimeError, match="TaskScheduler not available"):
            mgr.activate("no_sched")

    def test_run_once(self):
        from nova_ai.operators.manager import OperatorManager

        system = _make_system()
        system.ask = MagicMock(return_value={"content": "Tick done."})

        mgr = OperatorManager(system)
        m = OperatorManifest(
            id="run_test",
            name="Run",
            system_prompt="Test prompt",
            tools=["think"],
        )
        mgr.register(m)

        result = mgr.run_once("run_test")
        assert result == "Tick done."

        # Verify ask was called with correct params
        system.ask.assert_called_once()
        call_kwargs = system.ask.call_args
        assert call_kwargs.kwargs["agent"] == "operative"
        assert call_kwargs.kwargs["system_prompt"] == "Test prompt"
        assert call_kwargs.kwargs["operator_id"] == "run_test"


# ---------------------------------------------------------------------------
# TestOperativeAgent
# ---------------------------------------------------------------------------


class TestOperativeAgent:
    def test_init_defaults(self):
        from nova_ai.agents.operative import OperativeAgent

        engine = FakeEngine()
        with patch(
            "nova_ai.agents._stubs.load_config",
            side_effect=Exception("no config"),
        ):
            agent = OperativeAgent(engine, "test-model")
        assert agent.agent_id == "operative"
        assert agent._temperature == 0.3
        assert agent._max_tokens == 2048
        assert agent._max_turns == 20

    def test_accepts_tools(self):
        from nova_ai.agents.operative import OperativeAgent

        assert OperativeAgent.accepts_tools is True

    def test_run_with_system_prompt(self):
        from nova_ai.agents.operative import OperativeAgent

        engine = FakeEngine([{"content": "Response with prompt."}])
        agent = OperativeAgent(
            engine,
            "test-model",
            system_prompt="You are a test operator.",
        )
        result = agent.run("Execute tick")

        assert result.content == "Response with prompt."
        # Check system prompt was in messages
        call = engine.calls[0]
        messages = call["messages"]
        assert any(
            m.role.value == "system" and "test operator" in m.content for m in messages
        )

    def test_run_loads_session(self):
        from nova_ai.agents.operative import OperativeAgent

        session_store = FakeSessionStore()
        # Pre-populate session with history
        session = session_store.get_or_create("operator:test_op")
        session.messages = [
            {"role": "user", "content": "Previous tick"},
            {"role": "assistant", "content": "Previous response"},
        ]

        engine = FakeEngine([{"content": "New tick done."}])
        agent = OperativeAgent(
            engine,
            "test-model",
            operator_id="test_op",
            session_store=session_store,
        )
        result = agent.run("Execute tick")
        assert result.content == "New tick done."

    def test_run_saves_session(self):
        from nova_ai.agents.operative import OperativeAgent

        session_store = FakeSessionStore()

        engine = FakeEngine([{"content": "Tick response."}])
        agent = OperativeAgent(
            engine,
            "test-model",
            operator_id="save_test",
            session_store=session_store,
        )
        agent.run("Execute tick")

        saved = session_store._messages.get("operator:save_test", [])
        assert len(saved) == 2
        assert saved[0]["role"] == "user"
        assert saved[1]["role"] == "assistant"
        assert saved[1]["content"] == "Tick response."

    def test_run_recalls_state(self):
        from nova_ai.agents.operative import OperativeAgent

        memory = FakeMemoryBackend()
        memory.store("operator:recall_test:state", '{"last_run": "2024-01-01"}')

        engine = FakeEngine([{"content": "State recalled."}])
        agent = OperativeAgent(
            engine,
            "test-model",
            operator_id="recall_test",
            memory_backend=memory,
        )
        result = agent.run("Execute tick")
        assert result.content == "State recalled."

        # Verify state was injected into system prompt
        call = engine.calls[0]
        messages = call["messages"]
        sys_msgs = [m for m in messages if m.role.value == "system"]
        assert any("Previous State" in m.content for m in sys_msgs)

    def test_run_tool_loop(self):
        from nova_ai.agents.operative import OperativeAgent
        from nova_ai.tools._stubs import BaseTool

        # Mock tool
        tool = MagicMock(spec=BaseTool)
        tool.spec = MagicMock()
        tool.spec.name = "think"
        tool.spec.description = "Think about something"
        tool.spec.parameters = {}
        tool.spec.timeout_seconds = 30
        tool.spec.required_capabilities = []
        tool.spec.taint_labels = []
        tool.run = MagicMock(return_value="Thought result")

        engine = FakeEngine(
            [
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "name": "think",
                            "arguments": '{"thought": "test"}',
                        },
                    ],
                },
                {"content": "Final answer after tool use."},
            ]
        )

        agent = OperativeAgent(
            engine,
            "test-model",
            tools=[tool],
        )
        result = agent.run("Do something")
        assert result.content == "Final answer after tool use."
        assert result.turns == 2

    def test_run_without_persistence(self):
        from nova_ai.agents.operative import OperativeAgent

        engine = FakeEngine([{"content": "No persistence needed."}])
        agent = OperativeAgent(engine, "test-model")
        result = agent.run("Simple query")
        assert result.content == "No persistence needed."

    def test_run_auto_persists_state(self):
        from nova_ai.agents.operative import OperativeAgent

        memory = FakeMemoryBackend()

        engine = FakeEngine([{"content": "Tick complete."}])
        agent = OperativeAgent(
            engine,
            "test-model",
            operator_id="persist_test",
            memory_backend=memory,
        )
        agent.run("Execute tick")

        # State should be auto-persisted
        state = memory.retrieve("operator:persist_test:state")
        assert "Tick complete." in state

    def test_max_turns_exceeded(self):
        from nova_ai.agents.operative import OperativeAgent

        # Engine always returns tool calls, never a final answer
        responses = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": f"call_{i}",
                        "name": "think",
                        "arguments": '{"thought": "loop"}',
                    },
                ],
            }
            for i in range(25)
        ]
        engine = FakeEngine(responses)

        tool = MagicMock()
        tool.spec = MagicMock()
        tool.spec.name = "think"
        tool.spec.description = "Think"
        tool.spec.parameters = {}
        tool.spec.timeout_seconds = 30
        tool.spec.required_capabilities = []
        tool.spec.taint_labels = []
        tool.run = MagicMock(return_value="thought")

        agent = OperativeAgent(
            engine,
            "test-model",
            tools=[tool],
            max_turns=3,
        )
        result = agent.run("Loop forever")
        assert result.turns == 3
        assert result.metadata.get("max_turns_exceeded") is True


# ---------------------------------------------------------------------------
# TestSystemAskPassthrough
# ---------------------------------------------------------------------------


class TestSystemAskPassthrough:
    def test_system_prompt_forwarded(self):
        """system_prompt kwarg reaches the agent."""
        from nova_ai.system import NovaSystem

        engine = FakeEngine([{"content": "OK"}])
        system = _make_system(engine=engine)

        # Patch _run_agent to capture kwargs
        captured = {}

        def patched_run_agent(
            self,
            query,
            messages,
            agent_name,
            tool_names,
            temperature,
            max_tokens,
            **kwargs,
        ):
            captured.update(kwargs)
            return {"content": "OK"}

        from nova_ai.system import QueryOrchestrator

        with patch.object(QueryOrchestrator, "_run_agent", patched_run_agent):
            real_system = NovaSystem(
                config=system.config,
                bus=system.bus,
                engine=engine,
                engine_key="test",
                model="test-model",
                agent_name="operative",
            )
            real_system.ask("test", system_prompt="Custom prompt")

        assert captured.get("system_prompt") == "Custom prompt"

    def test_operator_id_forwarded(self):
        """operator_id kwarg reaches the agent."""
        from nova_ai.system import NovaSystem

        engine = FakeEngine([{"content": "OK"}])
        system = _make_system(engine=engine)

        captured = {}

        def patched_run_agent(
            self,
            query,
            messages,
            agent_name,
            tool_names,
            temperature,
            max_tokens,
            **kwargs,
        ):
            captured.update(kwargs)
            return {"content": "OK"}

        from nova_ai.system import QueryOrchestrator

        with patch.object(QueryOrchestrator, "_run_agent", patched_run_agent):
            real_system = NovaSystem(
                config=system.config,
                bus=system.bus,
                engine=engine,
                engine_key="test",
                model="test-model",
                agent_name="operative",
            )
            real_system.ask("test", operator_id="my_op")

        assert captured.get("operator_id") == "my_op"


# ---------------------------------------------------------------------------
# TestSchedulerOperatorExecution
# ---------------------------------------------------------------------------


class TestSchedulerOperatorExecution:
    def test_execute_task_with_operator_metadata(self):
        """Scheduler passes operator metadata through to system.ask()."""
        from nova_ai.scheduler.scheduler import ScheduledTask, TaskScheduler

        store = FakeSchedulerStore()
        mock_system = MagicMock()
        mock_system.ask = MagicMock(return_value="Tick result")

        scheduler = TaskScheduler(store, system=mock_system)

        task = ScheduledTask(
            id="operator:test_op",
            prompt="[OPERATOR TICK] Execute.",
            schedule_type="interval",
            schedule_value="300",
            agent="operative",
            tools="think,web_search",
            metadata={
                "operator_id": "test_op",
                "system_prompt": "You are a test operator.",
                "temperature": 0.3,
            },
        )
        store.save_task(task.to_dict())

        scheduler._execute_task(task)

        # Verify system.ask was called
        mock_system.ask.assert_called_once()
        call_kwargs = mock_system.ask.call_args
        # The scheduler passes agent and tools
        assert (
            call_kwargs.kwargs.get("agent") == "operative"
            or call_kwargs[1].get("agent") == "operative"
        )


# ---------------------------------------------------------------------------
# TestConfig
# ---------------------------------------------------------------------------


class TestOperatorsConfig:
    def test_config_defaults(self):
        from nova_ai.core.config import OperatorsConfig

        cfg = OperatorsConfig()
        assert cfg.enabled is False
        assert "operators" in cfg.manifests_dir
        assert cfg.auto_activate == ""

    def test_config_in_nova_config(self):
        from nova_ai.core.config import NovaConfig

        cfg = NovaConfig()
        assert hasattr(cfg, "operators")
        assert cfg.operators.enabled is False


# ---------------------------------------------------------------------------
# TestEvents
# ---------------------------------------------------------------------------


class TestOperatorEvents:
    def test_event_types_exist(self):
        from nova_ai.core.events import EventType

        assert hasattr(EventType, "OPERATOR_TICK_START")
        assert hasattr(EventType, "OPERATOR_TICK_END")
        assert EventType.OPERATOR_TICK_START.value == "operator_tick_start"
        assert EventType.OPERATOR_TICK_END.value == "operator_tick_end"


# ---------------------------------------------------------------------------
# TestAgentRegistration
# ---------------------------------------------------------------------------


class TestAgentRegistration:
    def test_operative_registered(self):
        from nova_ai.core.registry import AgentRegistry

        # Re-register if cleared by another test
        if not AgentRegistry.contains("operative"):
            from nova_ai.agents.operative import OperativeAgent

            AgentRegistry.register_value("operative", OperativeAgent)

        assert AgentRegistry.contains("operative")
        cls = AgentRegistry.get("operative")
        assert cls.__name__ == "OperativeAgent"


# ---------------------------------------------------------------------------
# TestLoadBundledOperators
# ---------------------------------------------------------------------------


class TestLoadBundledOperators:
    """Test that the bundled operator TOML files parse correctly."""

    @pytest.fixture
    def operators_dir(self):
        # Find the package-level operators/data/ directory
        here = Path(__file__).resolve()
        project_root = here.parent.parent.parent
        ops_dir = project_root / "src" / "nova_ai" / "operators" / "data"
        if not ops_dir.is_dir():
            pytest.skip("operators/data/ directory not found")
        return ops_dir

    def test_researcher_loads(self, operators_dir):
        from nova_ai.operators.loader import load_operator

        m = load_operator(operators_dir / "researcher.toml")
        assert m.id == "researcher"
        assert "web_search" in m.tools
        assert m.schedule_type == "interval"

    def test_news_digest_loads(self, operators_dir):
        from nova_ai.operators.loader import load_operator

        m = load_operator(operators_dir / "news_digest.toml")
        assert m.id == "news_digest"
        assert m.schedule_type == "cron"

    def test_knowledge_curator_loads(self, operators_dir):
        from nova_ai.operators.loader import load_operator

        m = load_operator(operators_dir / "knowledge_curator.toml")
        assert m.id == "knowledge_curator"
        assert "knowledge_add_entity" in m.tools

    def test_system_monitor_loads(self, operators_dir):
        from nova_ai.operators.loader import load_operator

        m = load_operator(operators_dir / "system_monitor.toml")
        assert m.id == "system_monitor"
        assert m.schedule_value == "300"


# ---------------------------------------------------------------------------
# TestOperatorGuardrails (manifest fields + loader)
# ---------------------------------------------------------------------------


class TestOperatorGuardrails:
    def test_manifest_guardrail_defaults(self):
        m = OperatorManifest(id="g", name="G")
        assert m.rate_limit_rpm == 0
        assert m.max_consecutive_failures == 0

    def test_loader_parses_guardrails(self, tmp_path):
        from nova_ai.operators.loader import load_operator

        toml_content = """\
[operator]
id = "guarded"
name = "Guarded"
rate_limit_rpm = 12
max_consecutive_failures = 5
required_capabilities = ["file:read", "network:fetch"]
"""
        p = tmp_path / "guarded.toml"
        p.write_text(toml_content)

        m = load_operator(p)
        assert m.rate_limit_rpm == 12
        assert m.max_consecutive_failures == 5
        assert m.required_capabilities == ["file:read", "network:fetch"]

    def test_activate_writes_guardrail_metadata(self):
        from nova_ai.operators.manager import OperatorManager
        from nova_ai.scheduler.scheduler import TaskScheduler

        store = FakeSchedulerStore()
        scheduler = TaskScheduler(store)
        system = _make_system(scheduler=scheduler)
        mgr = OperatorManager(system)

        m = OperatorManifest(
            id="guard_meta",
            name="GM",
            rate_limit_rpm=30,
            max_consecutive_failures=4,
            required_capabilities=["memory:read"],
        )
        mgr.register(m)
        mgr.activate("guard_meta")

        meta = store.get_task("operator:guard_meta")["metadata"]
        assert meta["rate_limit_rpm"] == 30
        assert meta["max_consecutive_failures"] == 4
        assert meta["required_capabilities"] == ["memory:read"]


# ---------------------------------------------------------------------------
# TestOperatorCapabilityEnforcement
# ---------------------------------------------------------------------------


class _AllowPolicy:
    """Capability policy that grants everything."""

    def check(self, agent_id: str, capability: str, resource: str = "") -> bool:
        return True


class _DenyPolicy:
    """Capability policy that denies everything (or a specific set)."""

    def __init__(self, denied: Optional[List[str]] = None) -> None:
        self.denied = set(denied or [])

    def check(self, agent_id: str, capability: str, resource: str = "") -> bool:
        return capability not in self.denied


class TestOperatorCapabilityEnforcement:
    def test_denied_capability_blocks_activation(self):
        from nova_ai.operators.manager import (
            OperatorCapabilityError,
            OperatorManager,
        )

        system = _make_system(scheduler=None)
        system.capability_policy = _DenyPolicy(denied=["file:write"])
        mgr = OperatorManager(system)
        mgr.register(
            OperatorManifest(
                id="locked",
                name="Locked",
                required_capabilities=["file:read", "file:write"],
            )
        )

        with pytest.raises(OperatorCapabilityError, match="file:write"):
            mgr.activate("locked")

    def test_granted_capability_allows_activation(self):
        from nova_ai.operators.manager import OperatorManager
        from nova_ai.scheduler.scheduler import TaskScheduler

        store = FakeSchedulerStore()
        scheduler = TaskScheduler(store)
        system = _make_system(scheduler=scheduler)
        system.capability_policy = _AllowPolicy()
        mgr = OperatorManager(system)
        mgr.register(
            OperatorManifest(
                id="allowed",
                name="Allowed",
                required_capabilities=["file:read"],
            )
        )

        task_id = mgr.activate("allowed")
        assert task_id == "operator:allowed"

    def test_no_policy_activates_open(self):
        """With no capability policy configured, activation proceeds."""
        from nova_ai.operators.manager import OperatorManager

        system = _make_system(scheduler=None)
        del system.capability_policy  # MagicMock: simulate absent attribute
        mgr = OperatorManager(system)
        mgr.register(
            OperatorManifest(
                id="open",
                name="Open",
                required_capabilities=["system:admin"],
            )
        )
        # RuntimeError comes from the *scheduler* check after capabilities
        # pass, proving the capability gate let it through.
        with pytest.raises(RuntimeError, match="TaskScheduler not available"):
            mgr.activate("open")

    def test_no_required_capabilities_skips_check(self):
        """Operators without required_capabilities never hit the policy."""
        from nova_ai.operators.manager import OperatorManager

        system = _make_system(scheduler=None)
        system.capability_policy = _DenyPolicy()  # denies everything
        mgr = OperatorManager(system)
        mgr.register(OperatorManifest(id="free", name="Free"))

        with pytest.raises(RuntimeError, match="TaskScheduler not available"):
            mgr.activate("free")

    def test_error_is_runtime_error(self):
        from nova_ai.operators.manager import OperatorCapabilityError

        assert issubclass(OperatorCapabilityError, RuntimeError)


# ---------------------------------------------------------------------------
# TestOperatorHealth
# ---------------------------------------------------------------------------


class TestOperatorHealth:
    def _setup(self):
        from nova_ai.operators.manager import OperatorManager
        from nova_ai.scheduler.scheduler import TaskScheduler

        store = FakeSchedulerStore()
        scheduler = TaskScheduler(store)
        system = _make_system(scheduler=scheduler)
        return store, system, OperatorManager(system)

    def _log_run(self, store, op_id, success, error=""):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        store.log_run(
            task_id=f"operator:{op_id}",
            started_at=now,
            finished_at=now,
            success=success,
            result="",
            error=error,
        )
        # bump last_run so stalled detection has a fresh heartbeat
        task_dict = store.get_task(f"operator:{op_id}")
        if task_dict is not None:
            task_dict["last_run"] = now
            store.update_task(task_dict)

    def test_inactive_when_never_activated(self):
        _, _, mgr = self._setup()
        mgr.register(OperatorManifest(id="ghost", name="Ghost"))

        health = {h["id"]: h for h in mgr.health()}
        assert health["ghost"]["health"] == "inactive"

    def test_pending_before_first_run(self):
        store, _, mgr = self._setup()
        mgr.register(OperatorManifest(id="fresh", name="Fresh"))
        mgr.activate("fresh")

        health = {h["id"]: h for h in mgr.health()}
        assert health["fresh"]["health"] == "pending"

    def test_healthy_after_success(self):
        store, _, mgr = self._setup()
        mgr.register(OperatorManifest(id="ok", name="OK"))
        mgr.activate("ok")
        self._log_run(store, "ok", success=True)

        health = {h["id"]: h for h in mgr.health()}
        assert health["ok"]["health"] == "healthy"
        assert health["ok"]["consecutive_failures"] == 0

    def test_failing_after_three_failures(self):
        store, _, mgr = self._setup()
        mgr.register(OperatorManifest(id="sick", name="Sick"))
        mgr.activate("sick")
        for i in range(3):
            self._log_run(store, "sick", success=False, error=f"err {i}")

        health = {h["id"]: h for h in mgr.health()}
        assert health["sick"]["health"] == "failing"
        assert health["sick"]["consecutive_failures"] == 3
        assert health["sick"]["last_error"] == "err 2"

    def test_degraded_with_recent_failure(self):
        store, _, mgr = self._setup()
        mgr.register(OperatorManifest(id="wobbly", name="Wobbly"))
        mgr.activate("wobbly")
        self._log_run(store, "wobbly", success=False, error="blip")
        self._log_run(store, "wobbly", success=True)

        health = {h["id"]: h for h in mgr.health()}
        assert health["wobbly"]["health"] == "degraded"
        assert health["wobbly"]["consecutive_failures"] == 0

    def test_stalled_overdue_interval_task(self):
        from datetime import datetime, timedelta, timezone

        store, _, mgr = self._setup()
        mgr.register(
            OperatorManifest(
                id="frozen",
                name="Frozen",
                schedule_type="interval",
                schedule_value="60",
            )
        )
        mgr.activate("frozen")
        # Heartbeat 10 minutes ago on a 60s interval -> 10x overdue
        stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        self._log_run(store, "frozen", success=True)
        task_dict = store.get_task("operator:frozen")
        task_dict["last_run"] = stale
        store.update_task(task_dict)

        health = {h["id"]: h for h in mgr.health()}
        assert health["frozen"]["health"] == "stalled"

    def test_paused_reports_paused(self):
        store, _, mgr = self._setup()
        mgr.register(OperatorManifest(id="nap", name="Nap"))
        mgr.activate("nap")
        self._log_run(store, "nap", success=True)
        mgr.pause("nap")

        health = {h["id"]: h for h in mgr.health()}
        assert health["nap"]["health"] == "paused"

    def test_health_includes_status_fields(self):
        store, _, mgr = self._setup()
        mgr.register(OperatorManifest(id="fields", name="Fields"))
        mgr.activate("fields")
        self._log_run(store, "fields", success=True)

        row = {h["id"]: h for h in mgr.health()}["fields"]
        assert row["status"] == "active"
        assert row["name"] == "Fields"
        assert row["last_run"] is not None


class TestRunOnceCapabilityGate:
    def test_run_once_respects_capability_denial(self):
        """Manual ticks go through the same RBAC gate as activation."""
        from nova_ai.operators.manager import (
            OperatorCapabilityError,
            OperatorManager,
        )

        system = _make_system()
        system.capability_policy = _DenyPolicy(denied=["file:write"])
        system.ask = MagicMock(return_value={"content": "tick"})
        mgr = OperatorManager(system)
        mgr.register(
            OperatorManifest(
                id="manual",
                name="Manual",
                required_capabilities=["file:write"],
            )
        )

        with pytest.raises(OperatorCapabilityError):
            mgr.run_once("manual")
        system.ask.assert_not_called()
