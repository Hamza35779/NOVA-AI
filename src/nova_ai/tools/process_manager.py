"""Process Manager tool — run and supervise background OS processes.

``shell_exec`` blocks until the child exits, so anything long-running (dev
servers, builds, test suites, watchers) cannot complete inside an agent turn.
This tool spawns detached jobs with stdout/stderr captured to log files and
lets the agent poll status, tail logs, and kill jobs across turns.

Stdlib only. Never uses a shell: *command* must be an argument list, which
keeps agent-supplied commands out of shell metacharacter trouble.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from nova_ai.core.paths import get_config_dir
from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.engine.self_optimizer import track_execution
from nova_ai.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_REGISTRY_FILENAME = "jobs.json"
_LOG_TAIL_DEFAULT = 50
_KILL_GRACE_SECONDS = 5.0


class _Job:
    """Book-keeping for one spawned process."""

    def __init__(
        self,
        job_id: str,
        name: str,
        command: List[str],
        cwd: str,
        pid: int,
        started_at: float,
        stdout_path: str,
        stderr_path: str,
    ) -> None:
        self.job_id = job_id
        self.name = name
        self.command = command
        self.cwd = cwd
        self.pid = pid
        self.started_at = started_at
        self.stdout_path = stdout_path
        self.stderr_path = stderr_path
        self._proc: Optional[subprocess.Popen] = None
        self.returncode: Optional[int] = None

    def to_record(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "command": self.command,
            "cwd": self.cwd,
            "pid": self.pid,
            "started_at": self.started_at,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "returncode": self.returncode,
        }

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "_Job":
        job = cls(
            job_id=record["job_id"],
            name=record.get("name", ""),
            command=list(record.get("command", [])),
            cwd=record.get("cwd", ""),
            pid=int(record.get("pid", -1)),
            started_at=float(record.get("started_at", 0.0)),
            stdout_path=record.get("stdout_path", ""),
            stderr_path=record.get("stderr_path", ""),
        )
        job.returncode = record.get("returncode")
        return job


@ToolRegistry.register("process_manager")
class ProcessManagerTool(BaseTool):
    """Spawn, poll, tail, and kill background OS processes."""

    tool_id = "process_manager"
    is_local = True

    def __init__(self, log_dir: Optional[str] = None) -> None:
        self._log_dir = Path(log_dir) if log_dir else get_config_dir() / "processes"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: Dict[str, _Job] = {}
        self._load_registry()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="process_manager",
            description=(
                "Run and supervise background OS processes. Actions: 'start' a "
                "command in the background (needs command as a list of program "
                "arguments, e.g. ['python', '-m', 'http.server']); 'status' to "
                "check whether a job is still running; 'logs' to tail its "
                "captured output; 'kill' to stop it; 'list' to show all jobs. "
                "Output is captured to log files so long-running work (servers, "
                "builds, test suites) survives across agent turns."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["start", "status", "logs", "kill", "list"],
                        "description": "Process operation to perform.",
                    },
                    "job_id": {
                        "type": "string",
                        "description": "Job id from a previous 'start' (for status, logs, kill).",
                    },
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Program and arguments to run, e.g. "
                            "['python', 'app.py']. Never a shell string."
                        ),
                    },
                    "name": {
                        "type": "string",
                        "description": "Human-readable label for the job.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Working directory for the child process.",
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Log lines to return for 'logs'. Default 50.",
                        "default": _LOG_TAIL_DEFAULT,
                    },
                },
                "required": ["action"],
            },
            category="system",
            requires_confirmation=True,
            timeout_seconds=30.0,
        )

    # -- registry persistence -------------------------------------------

    def _registry_path(self) -> Path:
        return self._log_dir / _REGISTRY_FILENAME

    def _load_registry(self) -> None:
        try:
            raw = self._registry_path().read_text(encoding="utf-8")
        except OSError:
            return
        try:
            records = json.loads(raw)
        except ValueError:
            logger.warning("Ignoring corrupt process registry %s", self._registry_path())
            return
        if isinstance(records, dict):
            for job_id, record in records.items():
                try:
                    job = _Job.from_record(record)
                except (KeyError, TypeError, ValueError):
                    continue
                self._jobs[job_id] = job

    def _save_registry(self) -> None:
        try:
            self._registry_path().write_text(
                json.dumps({jid: j.to_record() for jid, j in self._jobs.items()}, indent=1),
                encoding="utf-8",
            )
        except OSError:
            logger.warning("Could not persist process registry", exc_info=True)

    # -- job helpers ----------------------------------------------------

    def _refresh(self, job: _Job) -> None:
        """Update cached exit status from the live handle when available."""
        if job._proc is not None and job.returncode is None:
            job.returncode = job._proc.poll()
            if job.returncode is not None:
                self._save_registry()

    def _status_of(self, job: _Job) -> str:
        self._refresh(job)
        if job.returncode is None:
            return "running" if job._proc is not None else "detached"
        return "exited"

    def _tail(self, path: str, lines: int) -> str:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                data = fh.readlines()
        except OSError as exc:
            return f"[could not read log: {exc}]"
        return "".join(data[-lines:]) if lines > 0 else ""

    def _resolve_job(self, job_id: str) -> Optional[_Job]:
        return self._jobs.get((job_id or "").strip())

    # -- entry point -----------------------------------------------------

    @track_execution("process_manager")
    def execute(
        self,
        action: str,
        job_id: str = "",
        command: Any = None,
        name: str = "",
        cwd: str = "",
        lines: int = _LOG_TAIL_DEFAULT,
        **kwargs: Any,
    ) -> ToolResult:
        action = (action or "").lower().strip()
        if action == "start":
            return self._start(command, name, cwd)
        if action == "list":
            return self._list()
        if action not in ("status", "logs", "kill"):
            return ToolResult(
                tool_name="process_manager",
                content=f"Error: unknown action '{action}'. Use start, status, logs, kill, or list.",
                success=False,
            )
        job = self._resolve_job(job_id)
        if job is None:
            return ToolResult(
                tool_name="process_manager",
                content=f"Error: unknown job '{job_id}'. Use 'list' to show jobs.",
                success=False,
            )
        if action == "status":
            return self._status(job)
        if action == "logs":
            if not isinstance(lines, int) or isinstance(lines, bool):
                return ToolResult(
                    tool_name="process_manager",
                    content="Error: lines must be an integer.",
                    success=False,
                )
            return self._logs(job, lines)
        if action == "kill":
            return self._kill(job)
        # Unreachable: unknown actions are rejected before job resolution.
        return ToolResult(
            tool_name="process_manager",
            content=f"Error: unknown action '{action}'.",
            success=False,
        )

    # -- actions ----------------------------------------------------------

    def _start(self, command: Any, name: str, cwd: str) -> ToolResult:
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            return ToolResult(
                tool_name="process_manager",
                content="Error: command must be a non-empty list of strings, "
                "e.g. ['python', '-m', 'http.server'].",
                success=False,
            )
        workdir = cwd.strip() or "."
        if not Path(workdir).is_dir():
            return ToolResult(
                tool_name="process_manager",
                content=f"Error: working directory does not exist: {workdir}",
                success=False,
            )
        job_id = uuid.uuid4().hex[:8]
        stdout_path = str(self._log_dir / f"{job_id}.stdout.log")
        stderr_path = str(self._log_dir / f"{job_id}.stderr.log")
        try:
            stdout_fh = open(stdout_path, "w", encoding="utf-8", errors="replace")
            stderr_fh = open(stderr_path, "w", encoding="utf-8", errors="replace")
            try:
                proc = subprocess.Popen(
                    command,
                    cwd=workdir or None,
                    stdout=stdout_fh,
                    stderr=stderr_fh,
                )
            finally:
                stdout_fh.close()
                stderr_fh.close()
        except FileNotFoundError:
            return ToolResult(
                tool_name="process_manager",
                content=f"Error: program not found: {command[0]}",
                success=False,
            )
        except OSError as exc:
            return ToolResult(
                tool_name="process_manager",
                content=f"Error: could not start process: {exc}",
                success=False,
            )
        job = _Job(
            job_id=job_id,
            name=name.strip() or " ".join(command),
            command=list(command),
            cwd=workdir,
            pid=proc.pid,
            started_at=time.time(),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        job._proc = proc
        self._jobs[job_id] = job
        self._save_registry()
        return ToolResult(
            tool_name="process_manager",
            content=f"Started job '{job_id}' (pid {proc.pid}): {' '.join(command)}",
            success=True,
            metadata={"action": "start", "job_id": job_id, "pid": proc.pid},
        )

    def _status(self, job: _Job) -> ToolResult:
        state = self._status_of(job)
        detail = f"Job '{job.job_id}' ({job.name}): {state}"
        if job.returncode is not None:
            detail += f" (exit code {job.returncode})"
        return ToolResult(
            tool_name="process_manager",
            content=detail,
            success=True,
            metadata={
                "action": "status",
                "job_id": job.job_id,
                "state": state,
                "returncode": job.returncode,
                "pid": job.pid,
            },
        )

    def _logs(self, job: _Job, lines: int) -> ToolResult:
        out = self._tail(job.stdout_path, lines)
        err = self._tail(job.stderr_path, lines)
        content = f"--- stdout (last {lines} lines) ---\n{out}"
        if err.strip():
            content += f"\n--- stderr (last {lines} lines) ---\n{err}"
        return ToolResult(
            tool_name="process_manager",
            content=content or "(no output captured yet)",
            success=True,
            metadata={"action": "logs", "job_id": job.job_id},
        )

    def _kill(self, job: _Job) -> ToolResult:
        self._refresh(job)
        if job.returncode is not None:
            return ToolResult(
                tool_name="process_manager",
                content=f"Job '{job.job_id}' already exited (code {job.returncode}).",
                success=True,
                metadata={"action": "kill", "job_id": job.job_id},
            )
        if job._proc is None:
            return ToolResult(
                tool_name="process_manager",
                content=(
                    f"Job '{job.job_id}' is detached (manager restarted); "
                    f"cannot signal pid {job.pid} safely. Remove it from "
                    "the registry by deleting jobs.json if it is stale."
                ),
                success=False,
            )
        job._proc.terminate()
        try:
            job.returncode = job._proc.wait(timeout=_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            job._proc.kill()
            job.returncode = job._proc.wait()
        self._save_registry()
        return ToolResult(
            tool_name="process_manager",
            content=f"Killed job '{job.job_id}' (exit code {job.returncode}).",
            success=True,
            metadata={
                "action": "kill",
                "job_id": job.job_id,
                "returncode": job.returncode,
            },
        )

    def _list(self) -> ToolResult:
        if not self._jobs:
            return ToolResult(
                tool_name="process_manager",
                content="No background jobs.",
                success=True,
                metadata={"action": "list", "jobs": []},
            )
        rows = []
        infos = []
        for job in self._jobs.values():
            state = self._status_of(job)
            rows.append(f"- {job.job_id}: {job.name} [{state}] (pid {job.pid})")
            infos.append(
                {"job_id": job.job_id, "name": job.name, "state": state, "pid": job.pid}
            )
        return ToolResult(
            tool_name="process_manager",
            content="\n".join(rows),
            success=True,
            metadata={"action": "list", "jobs": infos},
        )


__all__ = ["ProcessManagerTool"]
