"""Test Runner tool — invoke pytest and parse failures into structured output.

Runs pytest in a subprocess against a target path (file or directory) with a
JUnit XML report, then parses the report into structured counts and per-test
failure details (stdlib xml.etree only; no pytest plugins required).

The target test suite's own code is executed under the local Python
interpreter, so like shell_exec this tool runs attacker-influenceable code
and requires confirmation.

Optional behaviour notes:
- Exit code 5 (no tests collected) is reported explicitly rather than
  treated as success.
- Console output is truncated in the response; the full failure set is in
  ``metadata["failures"]``.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.engine.self_optimizer import track_execution
from nova_ai.tools._stubs import BaseTool, ToolSpec

_TOOL_TIMEOUT = 600.0
_SUBPROCESS_TIMEOUT = 590.0


def _parse_junit(xml_path: Path) -> Dict[str, Any]:
    """Parse a JUnit XML report into structured counts and failure details."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")

    totals = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    duration = 0.0
    failures: List[Dict[str, str]] = []

    for suite in suites:
        totals["total"] += int(suite.get("tests", 0))
        totals["failed"] += int(suite.get("failures", 0))
        totals["errors"] += int(suite.get("errors", 0))
        totals["skipped"] += int(suite.get("skipped", 0))
        try:
            duration += float(suite.get("time", 0.0))
        except (TypeError, ValueError):
            pass

        for case in suite.iter("testcase"):
            node = case.find("failure")
            if node is None:
                node = case.find("error")
            if node is None:
                continue
            test_id = f"{case.get('classname', '')}::{case.get('name', '')}"
            detail = (node.text or "").strip()
            if len(detail) > 2000:
                detail = detail[:2000] + " ... [truncated]"
            failures.append(
                {
                    "test": test_id,
                    "type": node.tag,
                    "message": node.get("message", "") or "",
                    "detail": detail,
                }
            )

    totals["passed"] = totals["total"] - totals["failed"] - totals["errors"] - totals["skipped"]
    return {**totals, "duration_seconds": round(duration, 3), "failures": failures}


@ToolRegistry.register("test_runner")
class TestRunnerTool(BaseTool):
    """Run pytest on a path and return structured pass/fail results."""

    tool_id = "test_runner"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="test_runner",
            description=(
                "Run pytest against a test file or directory and return structured "
                "results: pass/fail/error/skip counts plus per-test failure details "
                "(test id, message, traceback excerpt). Executes the target test "
                "suite's code locally, so treat the path as trusted input. Use "
                "extra_args for pytest options like '-k pattern' or '-x'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "File or directory to test, passed to pytest as-is "
                            "(e.g. 'tests/tools/' or 'tests/tools/test_repl.py'). "
                            "Relative to the tool's working directory."
                        ),
                    },
                    "extra_args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional extra pytest command-line arguments, one "
                            "string per argument (e.g. ['-k', 'test_login', '-x']). "
                            "Do not pass output-format flags; the tool appends its "
                            "own JUnit XML report flag."
                        ),
                    },
                    "max_failure_details": {
                        "type": "integer",
                        "description": (
                            "Maximum number of failure detail blocks to include in "
                            "the response text. Defaults to 10; the full list is "
                            "always available in metadata."
                        ),
                    },
                },
                "required": ["path"],
            },
            category="testing",
            requires_confirmation=True,
            timeout_seconds=_TOOL_TIMEOUT,
        )

    @track_execution("test_runner")
    def execute(
        self,
        path: str,
        extra_args: List[str] | None = None,
        max_failure_details: int = 10,
        **kwargs: Any,
    ) -> ToolResult:
        if not path or not str(path).strip():
            return ToolResult(
                tool_name="test_runner",
                content="Error: no path provided. Pass a test file or directory for pytest.",
                success=False,
            )
        if extra_args is None:
            extra_args = []
        if not isinstance(extra_args, list) or not all(
            isinstance(a, str) for a in extra_args
        ):
            return ToolResult(
                tool_name="test_runner",
                content=(
                    "Error: extra_args must be a list of strings, one argument "
                    "per element (e.g. ['-k', 'test_login'])."
                ),
                success=False,
            )

        target = Path(path)
        if not target.exists():
            return ToolResult(
                tool_name="test_runner",
                content=f"Error: path does not exist: {target.resolve()}",
                success=False,
            )

        tmp = tempfile.NamedTemporaryFile(
            prefix="nova_test_runner_", suffix=".xml", delete=False
        )
        tmp.close()
        xml_path = Path(tmp.name)

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            str(target),
            "--junitxml",
            str(xml_path),
            "-p",
            "no:cacheprovider",
            *extra_args,
        ]

        started = time.time()
        try:
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=_SUBPROCESS_TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                return ToolResult(
                    tool_name="test_runner",
                    content=(
                        f"Error: pytest timed out after {_SUBPROCESS_TIMEOUT:.0f}s "
                        f"while testing {target}."
                    ),
                    success=False,
                    metadata={"path": str(target), "exit_code": None},
                )
            except OSError as exc:
                return ToolResult(
                    tool_name="test_runner",
                    content=f"Error: could not launch pytest — {exc}",
                    success=False,
                )
            elapsed = round(time.time() - started, 3)

            if not xml_path.exists():
                # pytest never wrote the report (usage error / crash before run).
                return ToolResult(
                    tool_name="test_runner",
                    content=(
                        f"Error: pytest produced no report (exit code {proc.returncode}). "
                        f"Last output:\n{(proc.stdout or proc.stderr or '')[-2000:]}"
                    ),
                    success=False,
                    metadata={"path": str(target), "exit_code": proc.returncode},
                )

            try:
                report = _parse_junit(xml_path)
            except ET.ParseError as exc:
                return ToolResult(
                    tool_name="test_runner",
                    content=(
                        f"Error: could not parse pytest report — {exc}. "
                        f"Last output:\n{(proc.stdout or proc.stderr or '')[-2000:]}"
                    ),
                    success=False,
                    metadata={"path": str(target), "exit_code": proc.returncode},
                )
        finally:
            try:
                xml_path.unlink(missing_ok=True)
            except OSError:
                pass

        if proc.returncode == 5:
            return ToolResult(
                tool_name="test_runner",
                content=(
                    f"No tests collected under {target}. Check the path and any "
                    "-k/-m filters in extra_args."
                ),
                success=False,
                metadata={
                    "path": str(target),
                    "exit_code": 5,
                    "wall_seconds": elapsed,
                    **report,
                },
            )

        report["exit_code"] = proc.returncode
        report["path"] = str(target)
        report["wall_seconds"] = elapsed

        counts_line = (
            f"{report['passed']} passed, {report['failed']} failed, "
            f"{report['errors']} errors, {report['skipped']} skipped"
        )
        if proc.returncode == 0:
            content = f"All tests passed: {counts_line} ({report['duration_seconds']}s)."
        else:
            content = f"Tests did not all pass: {counts_line} ({report['duration_seconds']}s)."
            for failure in report["failures"][: max(0, max_failure_details)]:
                content += (
                    f"\n\nFAILED {failure['test']}"
                    + (f" — {failure['message']}" if failure["message"] else "")
                    + (f"\n{failure['detail']}" if failure["detail"] else "")
                )
            remaining = len(report["failures"]) - max(0, max_failure_details)
            if remaining > 0:
                content += f"\n\n... and {remaining} more (see metadata.failures)."

        return ToolResult(
            tool_name="test_runner",
            content=content,
            success=proc.returncode == 0,
            metadata=report,
        )


__all__ = ["TestRunnerTool"]
