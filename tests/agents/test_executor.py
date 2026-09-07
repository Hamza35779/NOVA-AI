"""Tests for AgentExecutor single-tick execution."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nova_ai.agents._stubs import AgentResult
from nova_ai.agents.errors import FatalError, RetryableError
from nova_ai.core.events import EventBus, EventType


@pytest.fixture
def manager():
    from nova_ai.agents.manager import AgentManager

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        yield mgr
        mgr.close()


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def executor(manager, event_bus):
    from nova_ai.agents.executor import AgentExecutor

    mock_system = MagicMock()
    ex = AgentExecutor(manager=manager, event_bus=event_bus)
    ex.set_system(mock_system)
    return ex


class TestExecutorBasic:
    def test_execute_tick_publishes_start_end_events(
        self, executor, manager, event_bus
    ):
        agent = manager.create_agent(name="test", agent_type="monitor_operative")
        events = []
        event_bus.subscribe(EventType.AGENT_TICK_START, lambda e: events.append(e))
        event_bus.subscribe(EventType.AGENT_TICK_END, lambda e: events.append(e))

        rv = AgentResult(content="result text")
        with patch.object(executor, "_invoke_agent", return_value=rv):
            executor.execute_tick(agent["id"])

        assert len(events) == 2
        assert events[0].event_type == EventType.AGENT_TICK_START
        assert events[1].event_type == EventType.AGENT_TICK_END

    def test_execute_tick_updates_run_stats(self, executor, manager):
        agent = manager.create_agent(name="test", agent_type="monitor_operative")

        rv = AgentResult(content="result text")
        with patch.object(executor, "_invoke_agent", return_value=rv):
            executor.execute_tick(agent["id"])

        updated = manager.get_agent(agent["id"])
        assert updated["total_runs"] == 1
        assert updated["status"] == "idle"

    def test_execute_tick_sets_running_then_idle(self, executor, manager):
        agent = manager.create_agent(name="test", agent_type="monitor_operative")
        statuses = []

        original_start = manager.start_tick

        def track_start(aid):
            original_start(aid)
            statuses.append(manager.get_agent(aid)["status"])

        manager.start_tick = track_start

        rv = AgentResult(content="result")
        with patch.object(executor, "_invoke_agent", return_value=rv):
            executor.execute_tick(agent["id"])

        assert statuses == ["running"]
        assert manager.get_agent(agent["id"])["status"] == "idle"

    def test_execute_tick_handles_fatal_error(self, executor, manager, event_bus):
        agent = manager.create_agent(name="test", agent_type="monitor_operative")
        errors = []
        event_bus.subscribe(EventType.AGENT_TICK_ERROR, lambda e: errors.append(e))

        with patch.object(
            executor, "_invoke_agent", side_effect=FatalError("bad config")
        ):
            executor.execute_tick(agent["id"])

        assert manager.get_agent(agent["id"])["status"] == "error"
        assert len(errors) == 1

    def test_execute_tick_retries_retryable_error(self, executor, manager):
        agent = manager.create_agent(name="test", agent_type="monitor_operative")
        call_count = 0

        def flaky_invoke(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RetryableError("rate limit")
            return AgentResult(content="success")

        with patch.object(executor, "_invoke_agent", side_effect=flaky_invoke):
            with patch("nova_ai.agents.executor.retry_delay", return_value=0):
                executor.execute_tick(agent["id"])

        assert call_count == 3
        assert manager.get_agent(agent["id"])["status"] == "idle"

    def test_execute_tick_gives_up_after_max_retries(self, executor, manager):
        agent = manager.create_agent(name="test", agent_type="monitor_operative")

        with patch.object(
            executor, "_invoke_agent", side_effect=RetryableError("always fails")
        ):
            with patch("nova_ai.agents.executor.retry_delay", return_value=0):
                executor.execute_tick(agent["id"])

        assert manager.get_agent(agent["id"])["status"] == "error"

    def test_execute_tick_concurrency_guard(self, executor, manager):
        agent = manager.create_agent(name="test", agent_type="monitor_operative")
        manager.start_tick(agent["id"])  # Simulate already running

        # Second tick should handle the ValueError from start_tick
        rv = AgentResult(content="result")
        with patch.object(executor, "_invoke_agent", return_value=rv):
            executor.execute_tick(agent["id"])

        # Agent should still be running (first tick owns it)
        assert manager.get_agent(agent["id"])["status"] == "running"


def test_finalize_tick_reads_agent_result_metadata(tmp_path):
    """_finalize_tick() accumulates cost/tokens from AgentResult.metadata."""
    from nova_ai.agents.executor import AgentExecutor
    from nova_ai.agents.manager import AgentManager

    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus()
    executor = AgentExecutor(mgr, bus)

    agent = mgr.create_agent("budget-agent")
    mgr.start_tick(agent["id"])

    result = AgentResult(
        content="done",
        metadata={"tokens_used": 500, "cost": 0.05},
    )
    executor._finalize_tick(agent["id"], result, error=None, duration=1.0)

    updated = mgr.get_agent(agent["id"])
    assert updated["total_tokens"] == 500
    assert updated["total_cost"] == 0.05
    assert updated["stall_retries"] == 0
    mgr.close()


class TestPendingMessageDelivery:
    """Pending messages must survive a failed tick and be delivered on success.

    The delivery block used to run BEFORE agent.run(): a crashed tick marked
    the user's messages delivered without the agent ever seeing them.
    """

    def _make(self, tmp_path):
        from nova_ai.agents.executor import AgentExecutor
        from nova_ai.agents.manager import AgentManager

        mgr = AgentManager(str(tmp_path / "test.db"))
        executor = AgentExecutor(mgr, EventBus())
        agent = mgr.create_agent(name="msg-test", agent_type="monitor_operative")
        return mgr, executor, agent

    def test_failed_tick_keeps_messages_pending(self, tmp_path):
        mgr, executor, agent = self._make(tmp_path)
        mgr.send_message(agent["id"], "hello there")
        mgr.send_message(agent["id"], "second msg")

        with patch.object(
            executor,
            "_invoke_agent",
            side_effect=FatalError("api key not found"),
        ):
            executor.execute_tick(agent["id"])

        pending = mgr.get_pending_messages(agent["id"])
        assert [m["content"] for m in pending] == ["hello there", "second msg"]
        mgr.close()

    def test_successful_tick_marks_messages_delivered(self, tmp_path):
        from nova_ai.agents.executor import AgentExecutor
        from nova_ai.agents.manager import AgentManager

        # Delivery happens inside the real _invoke_agent, so drive it via the
        # registry path rather than patching _invoke_agent out.
        mgr = AgentManager(str(tmp_path / "test.db"))
        executor = AgentExecutor(mgr, EventBus())

        class FakeAgentCls:
            accepts_tools = False

            def __init__(self, engine, model, **kwargs):
                pass

            def run(self, text, context=None):
                return AgentResult(content="done", turns=1)

        agent = mgr.create_agent(name="msg-test", agent_type="monitor_operative")
        m1 = mgr.send_message(agent["id"], "hello there")
        m2 = mgr.send_message(agent["id"], "second msg")

        executor._system = MagicMock()
        executor._system.engine = MagicMock()
        executor._system.model = "test-model"
        executor._system.memory_backend = None
        executor._system.config = None

        import nova_ai.agents as agents_pkg

        with patch.object(agents_pkg, "AgentRegistry") as mock_reg:
            mock_reg.get.return_value = FakeAgentCls
            executor.execute_tick(agent["id"])

        assert mgr.get_pending_messages(agent["id"]) == []
        statuses = {m["id"]: m["status"] for m in mgr.list_messages(agent["id"])}
        assert statuses[m1["id"]] == "delivered"
        assert statuses[m2["id"]] == "delivered"
        mgr.close()
