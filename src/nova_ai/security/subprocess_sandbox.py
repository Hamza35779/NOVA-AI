"""Subprocess sandbox — secure process execution with environment isolation."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Safe environment variables to pass through
_SAFE_ENV_VARS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "TERM",
        "SHELL",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TZ",
        # Windows essentials: without SYSTEMROOT/SYSTEMDRIVE even Python's
        # socket/ssl modules fail to initialize inside the sandbox, and
        # shell=True resolves cmd.exe via COMSPEC.
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "COMSPEC",
        "USERPROFILE",
        "TEMP",
        "TMP",
    }
)


@dataclass(slots=True)
class SandboxResult:
    """Result of a sandboxed subprocess execution."""

    stdout: str = ""
    stderr: str = ""
    returncode: int = -1
    timed_out: bool = False
    killed: bool = False


def build_safe_env(
    passthrough: Optional[List[str]] = None,
    extra: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Build a sanitized environment dict.

    Only copies safe vars from current env, plus any in passthrough list.
    Extra vars are added directly.
    """
    env: Dict[str, str] = {}
    allowed = _SAFE_ENV_VARS | frozenset(passthrough or [])
    for key in allowed:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    if extra:
        env.update(extra)
    return env


def kill_process_tree(pid: int) -> None:
    """Kill a process and all its children (best effort)."""
    if sys.platform == "win32":
        # Windows has no process groups / SIGTERM; taskkill /T walks the tree.
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("Failed to kill process %d: %s", pid, exc)
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (OSError, ProcessLookupError) as exc:
        logger.debug("Failed to terminate process %d: %s", pid, exc)
    try:
        os.kill(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError) as exc:
        logger.debug("Failed to kill process %d: %s", pid, exc)


def run_sandboxed(
    command: str,
    *,
    timeout: float = 30.0,
    working_dir: Optional[str] = None,
    env_passthrough: Optional[List[str]] = None,
    env_extra: Optional[Dict[str, str]] = None,
    max_output_bytes: int = 102_400,
) -> SandboxResult:
    """Execute a command in a sandboxed subprocess.

    Features:
    - Clean environment (only safe vars passed through)
    - Timeout enforcement with process tree kill
    - Output truncation
    - New process group for clean cleanup
    """
    env = build_safe_env(passthrough=env_passthrough, extra=env_extra)
    cwd = working_dir if working_dir and os.path.isdir(working_dir) else None

    result = SandboxResult()
    try:
        # New process group / job for clean tree-kill. POSIX: setsid so the
        # child is its own process group (killpg-able). Windows has neither
        # preexec_fn nor setsid; CREATE_NEW_PROCESS_GROUP lets CTRL_BREAK /
        # taskkill target the tree.
        popen_kwargs: Dict[str, object] = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["preexec_fn"] = os.setsid
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=cwd,
            **popen_kwargs,  # type: ignore[arg-type]
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            result.stdout = stdout[:max_output_bytes] if stdout else ""
            result.stderr = stderr[:max_output_bytes] if stderr else ""
            result.returncode = proc.returncode
        except subprocess.TimeoutExpired:
            kill_process_tree(proc.pid)
            proc.wait(timeout=5)
            result.timed_out = True
            result.killed = True
            result.returncode = -1
            result.stdout = "(timed out)"
            result.stderr = ""
    except OSError as exc:
        result.stderr = f"Execution error: {exc}"
        result.returncode = -1

    return result


__all__ = ["SandboxResult", "build_safe_env", "kill_process_tree", "run_sandboxed"]
