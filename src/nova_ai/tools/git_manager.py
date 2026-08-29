"""Git Manager tool — perform Git operations from within the AI agent."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.engine.self_optimizer import track_execution
from nova_ai.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 16_000


def _run_git(args: List[str], cwd: str, timeout: int = 30) -> Dict[str, Any]:
    """Execute a git command and return structured output."""
    cmd = ["git"] + args
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        if len(stdout) > MAX_OUTPUT_CHARS:
            stdout = stdout[:MAX_OUTPUT_CHARS] + "\n...[output truncated]"

        return {
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "success": proc.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "Git command timed out",
            "success": False,
        }
    except FileNotFoundError:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "Git is not installed or not on PATH",
            "success": False,
        }


@ToolRegistry.register("git_manager")
class GitManagerTool(BaseTool):
    """Perform Git operations: status, diff, log, commit, branch, stash, and more."""

    tool_id = "git_manager"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="git_manager",
            description=(
                "Execute Git version control operations on a repository. "
                "Supports: status, diff, log, commit, branch, checkout, stash, add, push, pull, blame, and show."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "status",
                            "diff",
                            "diff_staged",
                            "log",
                            "log_oneline",
                            "commit",
                            "add",
                            "add_all",
                            "branch",
                            "branch_list",
                            "checkout",
                            "stash",
                            "stash_pop",
                            "push",
                            "pull",
                            "blame",
                            "show",
                            "reset",
                            "tag",
                        ],
                        "description": "Git operation to perform.",
                    },
                    "repo_path": {
                        "type": "string",
                        "description": "Path to the Git repository root directory.",
                    },
                    "args": {
                        "type": "string",
                        "description": "Additional arguments (e.g., file path for blame, commit message for commit, branch name for checkout).",
                    },
                },
                "required": ["action", "repo_path"],
            },
            category="development",
            timeout_seconds=30.0,
        )

    @track_execution("git_manager")
    def execute(
        self,
        action: str,
        repo_path: str,
        args: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        repo = Path(repo_path).resolve()
        if not repo.is_dir():
            return ToolResult(
                tool_name="git_manager",
                content=f"Directory not found: {repo_path}",
                success=False,
            )

        git_dir = repo / ".git"
        if not git_dir.exists() and action not in ("init",):
            return ToolResult(
                tool_name="git_manager",
                content=f"Not a Git repository: {repo_path}",
                success=False,
            )

        action = action.lower().strip()
        extra = [a for a in args.split() if a] if args else []

        command_map = {
            "status": ["status", "--short"],
            "diff": ["diff"] + extra,
            "diff_staged": ["diff", "--staged"] + extra,
            "log": ["log", "--oneline", "-20"] + extra,
            "log_oneline": ["log", "--oneline", "-30"] + extra,
            "add": ["add"] + (extra or ["."]),
            "add_all": ["add", "-A"],
            "commit": ["commit", "-m", args or "Auto-commit by NOVA AI"],
            "branch": ["branch", args] if args else ["branch"],
            "branch_list": ["branch", "-a"],
            "checkout": ["checkout"] + extra,
            "stash": ["stash", "push", "-m", args or "NOVA AI stash"],
            "stash_pop": ["stash", "pop"],
            "push": ["push"] + extra,
            "pull": ["pull"] + extra,
            "blame": ["blame"] + extra,
            "show": ["show"] + (extra or ["HEAD"]),
            "reset": ["reset"] + extra,
            "tag": ["tag"] + extra,
        }

        git_args = command_map.get(action)
        if git_args is None:
            return ToolResult(
                tool_name="git_manager",
                content=f"Unknown action: {action}. Supported: {', '.join(command_map.keys())}",
                success=False,
            )

        result = _run_git(git_args, str(repo))

        content = (
            result["stdout"]
            or result["stderr"]
            or f"git {action} completed (no output)"
        )
        if not result["success"] and result["stderr"]:
            content = f"Error: {result['stderr']}\n{result['stdout']}".strip()

        return ToolResult(
            tool_name="git_manager",
            content=content,
            success=result["success"],
            metadata={
                "action": action,
                "repo_path": str(repo),
                "returncode": result["returncode"],
            },
        )


__all__ = ["GitManagerTool"]
