"""Tests for ``nova dev-watch`` build/terminal diagnostics command."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from rich.console import Console

from nova_ai.cli.dev_watch_cmd import (
    DevWatchRun,
    _classify,
    _run_once,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# _classify — self-healing marker integration
# ---------------------------------------------------------------------------


class TestClassify:
    def test_zero_exit_clean_output_is_none(self) -> None:
        assert _classify(0, "all tests passed\n") is None

    def test_nonzero_exit_is_exit_code(self) -> None:
        category = _classify(1, "something went wrong")
        assert category == "exit_code"

    def test_traceback_marker_on_zero_exit(self) -> None:
        output = "running...\nTraceback (most recent call last):\n  File ..."
        assert _classify(0, output) == "error_output"

    def test_timeout_marker(self) -> None:
        assert _classify(-1, "execution timed out after 600s") == "timeout"

    def test_stderr_marker_on_zero_exit(self) -> None:
        assert _classify(0, "=== stderr ===\nerror: link failed") == "error_output"


# ---------------------------------------------------------------------------
# _run_once — subprocess handling
# ---------------------------------------------------------------------------


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class TestRunOnce:
    def test_passing_run(self) -> None:
        with patch.object(
            subprocess, "run", return_value=_proc(0, stdout="ok\n")
        ):
            run = _run_once("pytest -q", "off", 60, True, Console())
        assert run.status == "pass"
        assert run.returncode == 0
        assert run.failure_type is None
        assert run.suggestion == ""

    def test_failing_run_off_mode_no_consult(self) -> None:
        with patch.object(
            subprocess, "run", return_value=_proc(1, stderr="error: bad thing")
        ):
            run = _run_once("pytest -q", "off", 60, True, Console())
        assert run.status == "fail"
        assert run.returncode == 1
        assert run.suggestion == ""

    def test_failing_run_consults_healer(self) -> None:
        with patch.object(
            subprocess, "run", return_value=_proc(1, stdout="NameError: x")
        ), patch(
            "nova_ai.cli.dev_watch_cmd._consult_healer",
            return_value="Rename x to y in foo.py:12",
        ) as consult:
            run = _run_once("pytest -q", "suggest", 60, True, Console())
        assert run.status == "fail"
        assert run.suggestion == "Rename x to y in foo.py:12"
        args = consult.call_args.args
        assert args[0] == "pytest -q"
        assert args[2] == "exit_code"

    def test_zero_exit_embedded_error_consults_as_error_output(self) -> None:
        output = "Traceback (most recent call last):\n  File ..."
        with patch.object(
            subprocess, "run", return_value=_proc(0, stdout=output)
        ), patch(
            "nova_ai.cli.dev_watch_cmd._consult_healer",
            return_value="fix syntax",
        ) as consult:
            run = _run_once("pytest -q", "suggest", 60, True, Console())
        assert run.status == "fail"
        assert consult.call_args.args[2] == "error_output"

    def test_healer_failure_is_soft(self) -> None:
        with patch.object(
            subprocess, "run", return_value=_proc(1, stdout="boom")
        ), patch(
            "nova_ai.cli.dev_watch_cmd._consult_healer",
            side_effect=RuntimeError("no engine"),
        ):
            run = _run_once("pytest -q", "suggest", 60, True, Console())
        assert run.status == "fail"
        assert run.suggestion == ""

    def test_timeout(self) -> None:
        with patch.object(
            subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="x", timeout=5, output=b"part"),
        ):
            run = _run_once("pytest -q", "off", 5, True, Console())
        assert run.status == "fail"
        assert run.failure_type == "timeout"
        assert "timed out" in run.output

    def test_command_not_found(self) -> None:
        with patch.object(
            subprocess, "run", side_effect=FileNotFoundError("nope")
        ):
            run = _run_once("definitely-missing-cmd", "off", 60, True, Console())
        assert run.status == "fail"
        assert "command not found" in run.output


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


class TestCliWiring:
    def test_registered(self) -> None:
        from nova_ai.cli import cli

        assert "dev-watch" in cli.commands

    def test_help_smoke(self, runner) -> None:  # type: ignore[no-untyped-def]
        from nova_ai.cli import cli

        result = runner.invoke(cli, ["dev-watch", "--help"])
        assert result.exit_code == 0
        assert "--on-failure" in result.output

    def test_single_run_pass(self, runner) -> None:  # type: ignore[no-untyped-def]
        from nova_ai.cli import cli

        with patch.object(
            subprocess, "run", return_value=_proc(0, stdout="fine")
        ):
            result = runner.invoke(cli, ["dev-watch", "-c", "pytest -q"])
        assert result.exit_code == 0
        assert "PASS" in result.output

    def test_single_run_fail_with_suggestion(self, runner) -> None:  # type: ignore[no-untyped-def]
        from nova_ai.cli import cli

        failing = _proc(2, stderr="error: module not found")
        with patch.object(
            subprocess, "run", return_value=failing
        ), patch(
            "nova_ai.cli.dev_watch_cmd._consult_healer",
            return_value="Install the missing module.",
        ):
            result = runner.invoke(
                cli, ["dev-watch", "-c", "pytest -q", "--on-failure", "suggest"]
            )
        assert result.exit_code == 0
        assert "FAIL" in result.output
        assert "Install the missing module." in result.output
        assert "1/1 run(s) failed" in result.output


# ---------------------------------------------------------------------------
# DevWatchRun dataclass
# ---------------------------------------------------------------------------


class TestDevWatchRun:
    def test_defaults(self) -> None:
        run = DevWatchRun(
            command="x", returncode=0, status="pass", failure_type=None, output=""
        )
        assert run.suggestion == ""
