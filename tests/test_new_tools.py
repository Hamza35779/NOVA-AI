"""Tests for new NOVA AI tools: data analyzer, file converter, git manager, system monitor, code scaffolder, scheduler."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


class TestSelfOptimizer:
    def test_record_and_profile(self) -> None:
        from nova_ai.engine.self_optimizer import SelfOptimizer

        with tempfile.TemporaryDirectory() as tmpdir:
            opt = SelfOptimizer(persist_dir=Path(tmpdir))
            opt.record("test_tool", "execute", 150.0, True)
            opt.record("test_tool", "execute", 200.0, True)
            opt.record("test_tool", "execute", 50.0, False, error="timeout")

            profile = opt.get_profile("test_tool")
            assert profile["total_calls"] == 3
            assert profile["failures"] == 1
            assert profile["success_rate"] == pytest.approx(0.6667, abs=0.01)

    def test_health_report(self) -> None:
        from nova_ai.engine.self_optimizer import SelfOptimizer

        with tempfile.TemporaryDirectory() as tmpdir:
            opt = SelfOptimizer(persist_dir=Path(tmpdir))
            for _ in range(5):
                opt.record("healthy_tool", "exec", 100, True)
            for _ in range(5):
                opt.record("broken_tool", "exec", 100, False)

            report = opt.get_health_report()
            assert "broken_tool" in report["degraded_components"]
            assert "healthy_tool" in report["healthy_components"]

    def test_persistence(self) -> None:
        from nova_ai.engine.self_optimizer import SelfOptimizer

        with tempfile.TemporaryDirectory() as tmpdir:
            opt1 = SelfOptimizer(persist_dir=Path(tmpdir))
            opt1.record("persisted", "run", 50, True)
            opt1.persist()

            opt2 = SelfOptimizer(persist_dir=Path(tmpdir))
            profile = opt2.get_profile("persisted")
            assert profile["total_calls"] == 1


class TestTaskPlanner:
    def test_plan_execution(self) -> None:
        from nova_ai.engine.task_planner import TaskPlanner, TaskStatus

        planner = TaskPlanner()
        plan = planner.create_plan(
            "Test Goal",
            [
                {"id": "a", "title": "Step A"},
                {"id": "b", "title": "Step B", "depends_on": ["a"]},
            ],
        )
        result = planner.execute_plan(plan)
        assert result.status == TaskStatus.COMPLETED
        assert result.progress == 1.0

    def test_dependency_ordering(self) -> None:
        from nova_ai.engine.task_planner import TaskPlanner

        planner = TaskPlanner()
        plan = planner.create_plan(
            "Deps Test",
            [
                {"id": "c", "title": "Final", "depends_on": ["a", "b"]},
                {"id": "a", "title": "First"},
                {"id": "b", "title": "Second"},
            ],
        )
        ready = planner.get_ready_tasks(plan)
        ready_ids = [t.id for t in ready]
        assert "a" in ready_ids
        assert "b" in ready_ids
        assert "c" not in ready_ids


class TestDataAnalyzer:
    def test_csv_analysis(self) -> None:
        from nova_ai.tools.data_analyzer import DataAnalyzerTool

        csv_data = "name,age,score\nAlice,25,95\nBob,30,87\nCarol,22,91"
        tool = DataAnalyzerTool()
        result = tool.execute(raw_data=csv_data)
        assert result.success is True
        assert "age" in result.content
        assert "mean" in result.content.lower()

    def test_json_analysis(self) -> None:
        from nova_ai.tools.data_analyzer import DataAnalyzerTool

        json_data = json.dumps(
            [{"city": "NYC", "pop": 8000000}, {"city": "LA", "pop": 4000000}]
        )
        tool = DataAnalyzerTool()
        result = tool.execute(raw_data=json_data)
        assert result.success is True
        assert "Numeric" in result.content or "pop" in result.content

    def test_missing_input(self) -> None:
        from nova_ai.tools.data_analyzer import DataAnalyzerTool

        tool = DataAnalyzerTool()
        result = tool.execute()
        assert result.success is False


class TestFileConverter:
    def test_csv_to_json(self) -> None:
        from nova_ai.tools.file_converter import FileConverterTool

        tool = FileConverterTool()
        result = tool.execute(
            from_format="csv", to_format="json", raw_input="name,age\nAlice,25\nBob,30"
        )
        assert result.success is True
        parsed = json.loads(result.content)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "Alice"

    def test_markdown_to_html(self) -> None:
        from nova_ai.tools.file_converter import FileConverterTool

        tool = FileConverterTool()
        result = tool.execute(
            from_format="md", to_format="html", raw_input="# Hello\n\nWorld **bold**"
        )
        assert result.success is True
        assert "<h1>" in result.content
        assert "<strong>" in result.content

    def test_unsupported_conversion(self) -> None:
        from nova_ai.tools.file_converter import FileConverterTool

        tool = FileConverterTool()
        result = tool.execute(from_format="pdf", to_format="xlsx")
        assert result.success is False


class TestGitManager:
    def test_not_a_repo(self) -> None:
        from nova_ai.tools.git_manager import GitManagerTool

        with tempfile.TemporaryDirectory() as tmpdir:
            tool = GitManagerTool()
            result = tool.execute(action="status", repo_path=tmpdir)
            assert result.success is False
            assert "Not a Git repository" in result.content

    def test_invalid_directory(self) -> None:
        from nova_ai.tools.git_manager import GitManagerTool

        tool = GitManagerTool()
        result = tool.execute(action="status", repo_path="/nonexistent/path")
        assert result.success is False


class TestSystemMonitor:
    def test_basic_report(self) -> None:
        from nova_ai.tools.system_monitor import SystemMonitorTool

        tool = SystemMonitorTool()
        result = tool.execute()
        assert result.success is True
        assert "System Performance Report" in result.content
        assert "CPU" in result.content
        assert "Disk" in result.content


class TestCodeScaffolder:
    def test_python_package(self) -> None:
        from nova_ai.tools.code_scaffolder import CodeScaffolderTool

        with tempfile.TemporaryDirectory() as tmpdir:
            tool = CodeScaffolderTool()
            result = tool.execute(
                template="python_package", project_name="My Cool App", output_dir=tmpdir
            )
            assert result.success is True
            project_dir = Path(tmpdir) / "my_cool_app"
            assert (project_dir / "pyproject.toml").exists()
            assert (project_dir / "src" / "my_cool_app" / "__init__.py").exists()
            assert (project_dir / "tests" / "test_main.py").exists()

    def test_unknown_template(self) -> None:
        from nova_ai.tools.code_scaffolder import CodeScaffolderTool

        with tempfile.TemporaryDirectory() as tmpdir:
            tool = CodeScaffolderTool()
            result = tool.execute(
                template="nonexistent", project_name="test", output_dir=tmpdir
            )
            assert result.success is False


class TestScheduler:
    def test_schedule_and_list(self) -> None:
        from nova_ai.tools.scheduler_tool import SchedulerTool

        tool = SchedulerTool()
        result = tool.execute(action="schedule", name="Test Job", interval_seconds=9999)
        assert result.success is True
        assert "Test Job" in result.content

        list_result = tool.execute(action="list")
        assert list_result.success is True
        assert "Test Job" in list_result.content

    def test_cancel_job(self) -> None:
        from nova_ai.tools.scheduler_tool import SchedulerTool

        tool = SchedulerTool()
        result = tool.execute(
            action="schedule", name="Cancel Me", interval_seconds=9999
        )
        # Extract job ID from metadata
        job_id = result.metadata.get("job_id", "")
        cancel_result = tool.execute(action="cancel", job_id=job_id)
        assert cancel_result.success is True
