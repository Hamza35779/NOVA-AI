"""Tests for the process_manager tool. Spawns real short-lived processes only."""

from __future__ import annotations

import sys
import time

import pytest

from nova_ai.tools.process_manager import ProcessManagerTool


@pytest.fixture()
def tool(tmp_path) -> ProcessManagerTool:
    return ProcessManagerTool(log_dir=str(tmp_path / "procs"))


def _wait_for_exit(tool: ProcessManagerTool, job_id: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = tool.execute(action="status", job_id=job_id)
        if result.metadata["state"] == "exited":
            return
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not exit in time")


class TestProcessManagerSpec:
    def test_spec(self, tool: ProcessManagerTool):
        assert tool.spec.name == "process_manager"
        assert tool.spec.category == "system"
        assert tool.spec.requires_confirmation is True
        assert tool.spec.parameters["required"] == ["action"]


class TestProcessManagerStart:
    def test_start_and_status(self, tool: ProcessManagerTool):
        result = tool.execute(
            action="start",
            command=[sys.executable, "-c", "print('hello from job')"],
            name="hello",
        )
        assert result.success is True
        job_id = result.metadata["job_id"]
        _wait_for_exit(tool, job_id)
        status = tool.execute(action="status", job_id=job_id)
        assert status.metadata["state"] == "exited"
        assert status.metadata["returncode"] == 0

    def test_logs_capture_output(self, tool: ProcessManagerTool):
        result = tool.execute(
            action="start",
            command=[sys.executable, "-c", "print('line one'); print('line two')"],
        )
        assert result.success is True
        job_id = result.metadata["job_id"]
        _wait_for_exit(tool, job_id)
        logs = tool.execute(action="logs", job_id=job_id)
        assert logs.success is True
        assert "line one" in logs.content
        assert "line two" in logs.content

    def test_start_rejects_string_command(self, tool: ProcessManagerTool):
        result = tool.execute(action="start", command="python app.py")
        assert result.success is False
        assert "non-empty list of strings" in result.content

    def test_start_rejects_empty_command(self, tool: ProcessManagerTool):
        result = tool.execute(action="start", command=[])
        assert result.success is False

    def test_start_missing_program(self, tool: ProcessManagerTool):
        result = tool.execute(
            action="start", command=["definitely-not-a-real-program-xyz"]
        )
        assert result.success is False
        assert "not found" in result.content

    def test_start_bad_cwd(self, tool: ProcessManagerTool, tmp_path):
        result = tool.execute(
            action="start",
            command=[sys.executable, "-c", "pass"],
            cwd=str(tmp_path / "missing"),
        )
        assert result.success is False
        assert "does not exist" in result.content


class TestProcessManagerControl:
    def test_kill_running_job(self, tool: ProcessManagerTool):
        result = tool.execute(
            action="start",
            command=[sys.executable, "-c", "import time; time.sleep(60)"],
            name="sleeper",
        )
        assert result.success is True
        job_id = result.metadata["job_id"]
        killed = tool.execute(action="kill", job_id=job_id)
        assert killed.success is True
        assert "Killed" in killed.content
        status = tool.execute(action="status", job_id=job_id)
        assert status.metadata["state"] == "exited"

    def test_kill_finished_job(self, tool: ProcessManagerTool):
        result = tool.execute(
            action="start",
            command=[sys.executable, "-c", "pass"],
        )
        job_id = result.metadata["job_id"]
        _wait_for_exit(tool, job_id)
        killed = tool.execute(action="kill", job_id=job_id)
        assert killed.success is True
        assert "already exited" in killed.content

    def test_unknown_job(self, tool: ProcessManagerTool):
        result = tool.execute(action="status", job_id="nope1234")
        assert result.success is False
        assert "unknown job" in result.content

    def test_unknown_action(self, tool: ProcessManagerTool):
        result = tool.execute(action="explode")
        assert result.success is False
        assert "unknown action" in result.content

    def test_list_jobs(self, tool: ProcessManagerTool):
        empty = tool.execute(action="list")
        assert empty.success is True
        assert "No background jobs" in empty.content
        started = tool.execute(
            action="start",
            command=[sys.executable, "-c", "pass"],
            name="listed",
        )
        assert started.success is True
        listed = tool.execute(action="list")
        assert started.metadata["job_id"] in listed.content
        assert listed.metadata["jobs"][0]["name"] == "listed"

    def test_registry_survives_reload(self, tool: ProcessManagerTool, tmp_path):
        started = tool.execute(
            action="start",
            command=[sys.executable, "-c", "pass"],
            name="persisted",
        )
        assert started.success is True
        reloaded = ProcessManagerTool(log_dir=str(tmp_path / "procs"))
        listed = reloaded.execute(action="list")
        assert started.metadata["job_id"] in listed.content
