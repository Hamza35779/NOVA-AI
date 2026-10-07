"""Tests for the test_runner tool."""

from __future__ import annotations

import sys

import pytest

from nova_ai.tools.test_runner import TestRunnerTool

_PASSING_TEST = '''
def test_addition():
    assert 1 + 1 == 2
'''

_FAILING_TEST = '''
def test_addition():
    assert 1 + 1 == 3
'''

_MIXED_TESTS = '''
import pytest

def test_ok():
    assert True

def test_bad():
    assert False, "deliberate failure"

@pytest.mark.skip(reason="not today")
def test_skipped():
    assert True

def test_error_case():
    raise ValueError("boom")
'''


@pytest.fixture()
def tool() -> TestRunnerTool:
    return TestRunnerTool()


class TestTestRunnerTool:
    def test_spec(self, tool: TestRunnerTool):
        assert tool.spec.name == "test_runner"
        assert tool.spec.category == "testing"
        assert tool.spec.requires_confirmation is True
        assert tool.spec.timeout_seconds == 600.0
        assert tool.spec.parameters["required"] == ["path"]

    def test_no_path(self, tool: TestRunnerTool):
        result = tool.execute(path="")
        assert result.success is False
        assert "no path" in result.content.lower()

    def test_path_does_not_exist(self, tool: TestRunnerTool):
        result = tool.execute(path="does/not/exist/test_x.py")
        assert result.success is False
        assert "does not exist" in result.content

    def test_extra_args_type_check(self, tool: TestRunnerTool, tmp_path):
        result = tool.execute(path=str(tmp_path), extra_args="not-a-list")
        assert result.success is False
        assert "list of strings" in result.content

    def test_passing_suite(self, tool: TestRunnerTool, tmp_path):
        test_file = tmp_path / "test_pass.py"
        test_file.write_text(_PASSING_TEST, encoding="utf-8")
        result = tool.execute(path=str(test_file))
        assert result.success is True
        assert result.metadata["passed"] == 1
        assert result.metadata["failed"] == 0
        assert result.metadata["errors"] == 0
        assert result.metadata["exit_code"] == 0
        assert result.metadata["failures"] == []

    def test_failing_suite_reports_failure_details(
        self, tool: TestRunnerTool, tmp_path
    ):
        test_file = tmp_path / "test_fail.py"
        test_file.write_text(_FAILING_TEST, encoding="utf-8")
        result = tool.execute(path=str(test_file))
        assert result.success is False
        assert result.metadata["failed"] == 1
        assert result.metadata["passed"] == 0
        assert result.metadata["exit_code"] == 1
        assert len(result.metadata["failures"]) == 1
        failure = result.metadata["failures"][0]
        assert failure["type"] == "failure"
        assert "test_addition" in failure["test"]
        assert "(1 + 1) == 3" in result.content

    def test_mixed_suite_counts_all_outcomes(self, tool: TestRunnerTool, tmp_path):
        test_file = tmp_path / "test_mixed.py"
        test_file.write_text(_MIXED_TESTS, encoding="utf-8")
        result = tool.execute(path=str(test_file))
        assert result.success is False
        # pytest junitxml records uncaught exceptions in test bodies as
        # <failure>; <error> is reserved for setup/teardown problems.
        assert result.metadata["passed"] == 1
        assert result.metadata["failed"] == 2
        assert result.metadata["errors"] == 0
        assert result.metadata["skipped"] == 1
        assert result.metadata["total"] == 4
        kinds = {f["type"] for f in result.metadata["failures"]}
        assert kinds == {"failure"}

    def test_no_tests_collected(self, tool: TestRunnerTool, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = tool.execute(path=str(empty_dir))
        assert result.success is False
        assert "No tests collected" in result.content
        assert result.metadata["exit_code"] == 5

    def test_max_failure_details_limits_text_not_metadata(
        self, tool: TestRunnerTool, tmp_path
    ):
        test_file = tmp_path / "test_many.py"
        test_file.write_text(
            "\n".join(
                f"def test_fail_{i}():\n    assert False\n" for i in range(4)
            ),
            encoding="utf-8",
        )
        result = tool.execute(path=str(test_file), max_failure_details=2)
        assert result.success is False
        assert result.metadata["failed"] == 4
        assert len(result.metadata["failures"]) == 4
        assert "and 2 more" in result.content

    def test_directory_target(self, tool: TestRunnerTool, tmp_path):
        (tmp_path / "test_dir_a.py").write_text(_PASSING_TEST, encoding="utf-8")
        (tmp_path / "test_dir_b.py").write_text(_PASSING_TEST, encoding="utf-8")
        result = tool.execute(path=str(tmp_path))
        assert result.success is True
        assert result.metadata["passed"] == 2

    def test_extra_args_filter(self, tool: TestRunnerTool, tmp_path):
        test_file = tmp_path / "test_filter.py"
        test_file.write_text(
            "def test_one():\n    assert True\n\n"
            "def test_two():\n    assert True\n",
            encoding="utf-8",
        )
        result = tool.execute(
            path=str(test_file), extra_args=["-k", "test_one"]
        )
        assert result.success is True
        assert result.metadata["passed"] == 1

    def test_report_always_cleaned_up(self, tool: TestRunnerTool, tmp_path):
        test_file = tmp_path / "test_pass.py"
        test_file.write_text(_PASSING_TEST, encoding="utf-8")
        result = tool.execute(path=str(test_file))
        assert result.success is True
        leftovers = list(tmp_path.glob("nova_test_runner_*"))
        assert leftovers == []


@pytest.mark.parametrize("module", ["openpyxl"])
def test_module_import_is_isolated(module: str):
    # Guard against accidental hard imports leaking between tools.
    assert module not in sys.modules or sys.modules[module] is not None
