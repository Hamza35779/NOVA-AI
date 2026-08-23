"""Scheduler tool — cron-like recurring task automation and one-shot delayed execution."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from nova_ai.core.paths import get_config_dir
from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.engine.self_optimizer import track_execution
from nova_ai.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


@dataclass
class ScheduledJob:
    """Represents a scheduled task."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    name: str = ""
    description: str = ""
    interval_seconds: int = 0
    recurring: bool = False
    tool_name: Optional[str] = None
    tool_params: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_run: Optional[float] = None
    run_count: int = 0
    max_runs: int = 0  # 0 = unlimited for recurring
    active: bool = True


class TaskScheduler:
    """Lightweight in-process task scheduler with persistence.

    Supports:
    - One-shot delayed tasks
    - Recurring interval tasks
    - Named job management (list, cancel, pause)
    - Persistence across restarts
    """

    def __init__(self, persist_dir: Optional[Path] = None) -> None:
        self._persist_dir = persist_dir or (get_config_dir() / "scheduler")
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: Dict[str, ScheduledJob] = {}
        self._timers: Dict[str, threading.Timer] = {}
        self._executor: Optional[Callable] = None
        self._lock = threading.Lock()
        self._load_jobs()

    def set_executor(self, executor: Callable) -> None:
        """Set the tool executor callback: fn(tool_name, params) -> ToolResult."""
        self._executor = executor

    def schedule(
        self,
        name: str,
        interval_seconds: int,
        recurring: bool = False,
        tool_name: Optional[str] = None,
        tool_params: Optional[Dict[str, Any]] = None,
        max_runs: int = 0,
        description: str = "",
    ) -> ScheduledJob:
        """Schedule a new task."""
        job = ScheduledJob(
            name=name,
            description=description,
            interval_seconds=max(interval_seconds, 1),
            recurring=recurring,
            tool_name=tool_name,
            tool_params=tool_params or {},
            max_runs=max_runs,
        )

        with self._lock:
            self._jobs[job.id] = job
            self._persist_jobs()

        self._start_timer(job)
        logger.info(
            "Scheduled job '%s' (id=%s, interval=%ds, recurring=%s)",
            name,
            job.id,
            interval_seconds,
            recurring,
        )
        return job

    def cancel(self, job_id: str) -> bool:
        """Cancel a scheduled job."""
        with self._lock:
            if job_id not in self._jobs:
                return False
            self._jobs[job_id].active = False
            timer = self._timers.pop(job_id, None)
            if timer:
                timer.cancel()
            self._persist_jobs()
        return True

    def list_jobs(self) -> List[Dict[str, Any]]:
        """List all scheduled jobs."""
        with self._lock:
            results = []
            for job in self._jobs.values():
                results.append(
                    {
                        "id": job.id,
                        "name": job.name,
                        "description": job.description,
                        "interval_seconds": job.interval_seconds,
                        "recurring": job.recurring,
                        "active": job.active,
                        "run_count": job.run_count,
                        "max_runs": job.max_runs,
                        "last_run": job.last_run,
                        "tool_name": job.tool_name,
                    }
                )
            return results

    def _start_timer(self, job: ScheduledJob) -> None:
        """Start the background timer for a job."""
        if not job.active:
            return

        def _run() -> None:
            if not job.active:
                return

            job.last_run = time.time()
            job.run_count += 1
            logger.info("Running scheduled job '%s' (run #%d)", job.name, job.run_count)

            if job.tool_name and self._executor:
                try:
                    self._executor(job.tool_name, job.tool_params)
                except Exception as e:
                    logger.error("Scheduled job '%s' failed: %s", job.name, e)

            # Check if max runs reached
            if job.max_runs > 0 and job.run_count >= job.max_runs:
                job.active = False
                with self._lock:
                    self._persist_jobs()
                return

            # Reschedule if recurring
            if job.recurring and job.active:
                self._start_timer(job)

            with self._lock:
                self._persist_jobs()

        timer = threading.Timer(job.interval_seconds, _run)
        timer.daemon = True
        timer.name = f"scheduler-{job.id}"

        with self._lock:
            old = self._timers.pop(job.id, None)
            if old:
                old.cancel()
            self._timers[job.id] = timer

        timer.start()

    def _load_jobs(self) -> None:
        """Load persisted jobs from disk."""
        jobs_file = self._persist_dir / "jobs.json"
        if not jobs_file.exists():
            return
        try:
            data = json.loads(jobs_file.read_text(encoding="utf-8"))
            for raw in data:
                job = ScheduledJob(**{k: v for k, v in raw.items() if k != "id"})
                job.id = raw.get("id", job.id)
                self._jobs[job.id] = job
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning("Failed to load scheduler jobs: %s", e)

    def _persist_jobs(self) -> None:
        """Save jobs to disk. Caller must hold lock."""
        jobs_file = self._persist_dir / "jobs.json"
        data = []
        for job in self._jobs.values():
            data.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "description": job.description,
                    "interval_seconds": job.interval_seconds,
                    "recurring": job.recurring,
                    "tool_name": job.tool_name,
                    "tool_params": job.tool_params,
                    "created_at": job.created_at,
                    "last_run": job.last_run,
                    "run_count": job.run_count,
                    "max_runs": job.max_runs,
                    "active": job.active,
                }
            )
        jobs_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def shutdown(self) -> None:
        """Cancel all running timers."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
            self._persist_jobs()


# ── Tool Registration ──────────────────────────────────────────

_global_scheduler: Optional[TaskScheduler] = None
_sched_lock = threading.Lock()


def get_scheduler() -> TaskScheduler:
    """Get or create the global TaskScheduler instance."""
    global _global_scheduler
    if _global_scheduler is None:
        with _sched_lock:
            if _global_scheduler is None:
                _global_scheduler = TaskScheduler()
    return _global_scheduler


@ToolRegistry.register("task_scheduler")
class SchedulerTool(BaseTool):
    """Schedule one-shot or recurring automated tasks."""

    tool_id = "task_scheduler"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="task_scheduler",
            description=(
                "Schedule automated tasks: one-shot delayed execution or recurring interval jobs. "
                "Can trigger any registered tool on a timer. Manages job lifecycle (list, cancel)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["schedule", "list", "cancel"],
                        "description": "Scheduler operation.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Job name (for schedule action).",
                    },
                    "interval_seconds": {
                        "type": "integer",
                        "description": "Delay/interval in seconds.",
                    },
                    "recurring": {
                        "type": "boolean",
                        "description": "Repeat on interval.",
                        "default": False,
                    },
                    "tool_name": {
                        "type": "string",
                        "description": "Tool to execute when fired.",
                    },
                    "tool_params": {
                        "type": "object",
                        "description": "Parameters for the tool.",
                    },
                    "max_runs": {
                        "type": "integer",
                        "description": "Max runs for recurring (0 = unlimited).",
                        "default": 0,
                    },
                    "job_id": {
                        "type": "string",
                        "description": "Job ID (for cancel action).",
                    },
                },
                "required": ["action"],
            },
            category="automation",
            timeout_seconds=5.0,
        )

    @track_execution("task_scheduler")
    def execute(self, action: str, **kwargs: Any) -> ToolResult:
        scheduler = get_scheduler()
        action = action.lower().strip()

        if action == "list":
            jobs = scheduler.list_jobs()
            if not jobs:
                return ToolResult(
                    tool_name="task_scheduler",
                    content="No scheduled jobs.",
                    success=True,
                )
            lines = ["## Scheduled Jobs", ""]
            for j in jobs:
                status = "🟢 Active" if j["active"] else "⏸️ Paused"
                lines.append(
                    f"- **{j['name']}** (`{j['id']}`) — {status} | "
                    f"Interval: {j['interval_seconds']}s | Runs: {j['run_count']}"
                )
            return ToolResult(
                tool_name="task_scheduler", content="\n".join(lines), success=True
            )

        elif action == "cancel":
            job_id = kwargs.get("job_id", "")
            if not job_id:
                return ToolResult(
                    tool_name="task_scheduler",
                    content="Error: job_id required for cancel.",
                    success=False,
                )
            ok = scheduler.cancel(job_id)
            msg = f"Cancelled job {job_id}" if ok else f"Job {job_id} not found"
            return ToolResult(tool_name="task_scheduler", content=msg, success=ok)

        elif action == "schedule":
            name = kwargs.get("name", "Unnamed Task")
            interval = kwargs.get("interval_seconds", 60)
            recurring = kwargs.get("recurring", False)
            tool_name = kwargs.get("tool_name")
            tool_params = kwargs.get("tool_params", {})
            max_runs = kwargs.get("max_runs", 0)

            job = scheduler.schedule(
                name=name,
                interval_seconds=interval,
                recurring=recurring,
                tool_name=tool_name,
                tool_params=tool_params,
                max_runs=max_runs,
            )
            return ToolResult(
                tool_name="task_scheduler",
                content=(
                    f"✅ Scheduled '{name}' (ID: {job.id})\n"
                    f"  Interval: {interval}s | Recurring: {recurring} | Tool: {tool_name or 'none'}"
                ),
                success=True,
                metadata={"job_id": job.id, "name": name},
            )

        return ToolResult(
            tool_name="task_scheduler",
            content=f"Unknown action: {action}",
            success=False,
        )


__all__ = ["SchedulerTool", "TaskScheduler", "get_scheduler"]
