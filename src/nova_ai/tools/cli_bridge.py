"""CLI Bridge tool — integrates with external coding & agent CLIs (Claude Code, Gemini CLI, OpenCode, Codex, Aider)."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 32 * 1024  # 32KB cap on combined stdout/stderr returned to the model
DEFAULT_TIMEOUT_SECONDS = 180.0
MAX_TIMEOUT_SECONDS = 900.0

# Shell metacharacters that must never appear in a prompt passed as a subprocess argument.
_RE_SHELL_METACHARS = re.compile(r"[;&|`$><\(\)\{\}\[\]!\\\x00-\x08\x0b\x0c\x0e-\x1f]")

SUPPORTED_CLIS: Dict[str, Dict[str, Any]] = {
    "claude": {
        "name": "Claude Code CLI",
        "binary": "claude",
        "description": "Anthropic's official Claude Code CLI for terminal-based code editing and autonomous agents.",
        "install_cmd": "npm install -g @anthropic-ai/claude-code",
        # Non-interactive print mode so batch invocations never hang on the interactive REPL.
        # Permission prompts are intentionally NOT skipped by default.
        "default_flags": ["-p"],
    },
    "gemini": {
        "name": "Gemini CLI",
        "binary": "gemini",
        "description": "Google Gemini CLI for command-line prompts, code generation, and multi-file editing.",
        "install_cmd": "pip install gemini-cli or npm install -g gemini-cli",
        "default_flags": ["-p"],
    },
    "opencode": {
        "name": "OpenCode CLI",
        "binary": "opencode",
        "description": "OpenCode agentic developer CLI for project scaffolding, refactoring, and test suites.",
        "install_cmd": "npm install -g opencode-cli",
        "default_flags": ["run"],
    },
    "codex": {
        "name": "Codex CLI",
        "binary": "codex",
        "description": "Terminal Codex assistant for shell commands and script authoring.",
        "install_cmd": "pip install codex-cli",
        "default_flags": ["exec"],
    },
    "aider": {
        "name": "Aider AI Pair Programmer",
        "binary": "aider",
        "description": "Terminal-based AI pair programming tool with git repository integration.",
        "install_cmd": "pip install aider-chat",
        # --yes-always auto-accepts suggested edits; --no-checkout keeps the worktree clean.
        "default_flags": ["--yes-always", "--no-auto-commits"],
    },
}


def _truncate_output(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Cap output length so a runaway CLI cannot flood the tool result."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return f"{cut}\n\n[output truncated at {limit} characters — {len(text) - limit} more omitted]"


def _validate_prompt(prompt: str) -> Optional[str]:
    """Return an error message if the prompt is unsafe/invalid, else None.

    The prompt is passed as an argv entry with ``shell=False``, which already
    prevents shell injection; this is defense-in-depth against future refactors
    that might toggle ``shell=True`` or route through a different executor.
    """
    if not prompt or not prompt.strip():
        return "Error: prompt is required and cannot be empty."
    if "\x00" in prompt:
        return "Error: prompt contains null bytes."
    suspicious = _RE_SHELL_METACHARS.search(prompt)
    if suspicious:
        return (
            f"Error: prompt contains shell metacharacter {suspicious.group(0)!r}. "
            "Remove special characters or pass flags via the 'flags' parameter."
        )
    if len(prompt) > 100_000:
        return "Error: prompt exceeds maximum length of 100,000 characters."
    return None


@ToolRegistry.register("cli_agent_bridge")
class CLIBridgeTool(BaseTool):
    """Tool to invoke and orchestrate external coding agent CLIs."""

    tool_id = "cli_agent_bridge"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="cli_agent_bridge",
            description=(
                "Invoke and coordinate external coding CLIs (Claude Code, Gemini CLI, OpenCode, Codex, Aider) "
                "to execute complex coding tasks, build files, run test suites, or generate repositories."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "cli_name": {
                        "type": "string",
                        "enum": [
                            "claude",
                            "gemini",
                            "opencode",
                            "codex",
                            "aider",
                            "custom",
                        ],
                        "description": (
                            "Which CLI agent tool to invoke. Use 'custom' together with "
                            "'binary_path' to run any CLI available on the system."
                        ),
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Task instruction or prompt to pass to the CLI tool.",
                    },
                    "working_directory": {
                        "type": "string",
                        "description": "Target project directory path (defaults to current directory).",
                    },
                    "flags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of additional CLI flags (e.g. ['--model', 'gpt-5']).",
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "description": "Maximum seconds to wait for the CLI before aborting (30-900, default 180).",
                        "default": DEFAULT_TIMEOUT_SECONDS,
                    },
                    "use_default_flags": {
                        "type": "boolean",
                        "description": "Prepend per-CLI smart defaults (auto-confirm / non-interactive modes). Default true.",
                        "default": True,
                    },
                    "binary_path": {
                        "type": "string",
                        "description": "Explicit executable path — required when cli_name is 'custom'.",
                    },
                },
                "required": ["cli_name", "prompt"],
            },
            category="development",
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        )

    def execute(
        self,
        cli_name: str,
        prompt: str,
        working_directory: Optional[str] = None,
        flags: Optional[List[str]] = None,
        timeout_seconds: Optional[float] = None,
        use_default_flags: bool = True,
        binary_path: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        cli_key = cli_name.lower().strip()
        cwd = working_directory or os.getcwd()

        cli_meta = SUPPORTED_CLIS.get(cli_key)

        # Resolve binary
        if cli_key == "custom":
            if not binary_path:
                return ToolResult(
                    tool_name="cli_agent_bridge",
                    content=(
                        "Error: cli_name='custom' requires an explicit 'binary_path' parameter. "
                        f"Known CLIs: {', '.join(SUPPORTED_CLIS.keys())}."
                    ),
                    success=False,
                    metadata={"cli": cli_key, "found": False},
                )
            bin_name = binary_path
        else:
            bin_name = (cli_meta or {}).get("binary", cli_key)

        resolved_bin = shutil.which(bin_name) or (
            bin_name if Path(bin_name).is_file() else None
        )

        if not resolved_bin:
            install_hint = (cli_meta or {}).get("install_cmd", f"install {bin_name}")
            display_name = (cli_meta or {}).get("name", cli_name)
            return ToolResult(
                tool_name="cli_agent_bridge",
                content=(
                    f"CLI binary '{bin_name}' not found on system PATH.\n"
                    f"To install {display_name}, run:\n"
                    f"  {install_hint}\n"
                    f"Or pass standard shell commands to the local shell executor."
                ),
                success=False,
                metadata={"cli": cli_key, "found": False, "install_hint": install_hint},
            )

        prompt_error = _validate_prompt(prompt)
        if prompt_error:
            return ToolResult(
                tool_name="cli_agent_bridge",
                content=prompt_error,
                success=False,
                metadata={"cli": cli_key},
            )

        # Validate working directory exists
        if not Path(cwd).is_dir():
            return ToolResult(
                tool_name="cli_agent_bridge",
                content=f"Error: working_directory '{cwd}' does not exist.",
                success=False,
                metadata={"cli": cli_key},
            )

        # Timeout handling: spec default, overridable per call, hard-capped.
        try:
            timeout = (
                float(timeout_seconds)
                if timeout_seconds is not None
                else DEFAULT_TIMEOUT_SECONDS
            )
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT_SECONDS
        timeout = max(1.0, min(timeout, MAX_TIMEOUT_SECONDS))

        # Compose command: smart per-CLI defaults first, then user overrides, then prompt.
        cmd: List[str] = [resolved_bin]
        if use_default_flags and cli_meta:
            cmd.extend(cli_meta.get("default_flags", []))
        cmd.extend(flags or [])
        cmd.append(prompt)

        logger.info(
            "Executing CLI agent command: %s in %s (timeout=%ss)", cmd[:4], cwd, timeout
        )
        start_ts = time.perf_counter()

        try:
            res = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            duration = round(time.perf_counter() - start_ts, 2)
            logger.warning(
                "CLI agent '%s' timed out after %.1fs in %s", cli_key, duration, cwd
            )
            return ToolResult(
                tool_name="cli_agent_bridge",
                content=f"Error: {cli_name} execution timed out after {int(timeout)} seconds.",
                success=False,
                metadata={
                    "cli": cli_key,
                    "timeout_seconds": timeout,
                    "duration_seconds": duration,
                },
            )
        except Exception as exc:
            return ToolResult(
                tool_name="cli_agent_bridge",
                content=f"Error executing {cli_name}: {exc}",
                success=False,
                metadata={"cli": cli_key},
            )

        duration = round(time.perf_counter() - start_ts, 2)
        stdout = _truncate_output((res.stdout or "").strip())
        stderr = _truncate_output((res.stderr or "").strip())
        combined = stdout if not stderr else f"{stdout}\n\n[stderr]\n{stderr}".strip()
        combined = _truncate_output(combined)

        success = res.returncode == 0
        logger.info(
            "CLI agent '%s' finished in %.2fs with returncode %d",
            cli_key,
            duration,
            res.returncode,
        )
        return ToolResult(
            tool_name="cli_agent_bridge",
            content=combined or f"Command finished with exit code {res.returncode}",
            success=success,
            metadata={
                "cli": cli_key,
                "returncode": res.returncode,
                "cwd": cwd,
                "duration_seconds": duration,
                "timeout_seconds": timeout,
                "truncated": len(res.stdout or "") + len(res.stderr or "")
                > MAX_OUTPUT_CHARS,
            },
        )


__all__ = ["CLIBridgeTool", "SUPPORTED_CLIS"]
