"""Task Planner — multi-step task decomposition, dependency resolution, and execution orchestration.

Breaks complex user requests into atomic subtasks, resolves dependencies,
executes them in optimal order, and tracks progress with retry logic.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from nova_ai.engine.self_optimizer import get_optimizer

logger = logging.getLogger(__name__)

# Per-plan asyncio event queues for SSE streaming.
# Key: plan_id, Value: list of asyncio.Queue instances (one per SSE subscriber).
_plan_queues: dict[str, list] = defaultdict(list)
_queues_lock = threading.Lock()


def _emit_task_event(plan_id: str, event: dict) -> None:
    """Push a task status event to all SSE subscribers for a plan."""
    payload = json.dumps(event)
    with _queues_lock:
        queues = _plan_queues.get(plan_id, [])
    for q in queues:
        try:
            q.put_nowait(payload)
        except Exception:
            pass


def subscribe_to_plan(plan_id: str, queue) -> None:
    """Register an asyncio.Queue to receive events for a plan."""
    with _queues_lock:
        _plan_queues[plan_id].append(queue)


def unsubscribe_from_plan(plan_id: str, queue) -> None:
    """Remove a subscriber queue for a plan."""
    with _queues_lock:
        if plan_id in _plan_queues:
            try:
                _plan_queues[plan_id].remove(queue)
            except ValueError:
                pass



class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


@dataclass
class SubTask:
    """Atomic unit of work within a plan."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = ""
    description: str = ""
    tool_name: Optional[str] = None
    tool_params: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str = ""
    duration_ms: float = 0.0
    retries: int = 0
    max_retries: int = 2


@dataclass
class TaskPlan:
    """Ordered execution plan with dependency graph."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    goal: str = ""
    tasks: List[SubTask] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    @property
    def progress(self) -> float:
        if not self.tasks:
            return 0.0
        done = sum(
            1
            for t in self.tasks
            if t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
        )
        return round(done / len(self.tasks), 3)

    @property
    def summary(self) -> Dict[str, Any]:
        counts = {}
        for t in self.tasks:
            counts[t.status.value] = counts.get(t.status.value, 0) + 1
        return {
            "plan_id": self.id,
            "goal": self.goal,
            "total_tasks": len(self.tasks),
            "progress": f"{self.progress:.0%}",
            "status_breakdown": counts,
            "overall_status": self.status.value,
        }


class TaskPlanner:
    """Decomposes complex goals into executable subtask pipelines.

    Features:
    - DAG-based dependency resolution
    - Parallel-ready execution batching
    - Automatic retry with backoff for failed tasks
    - Progress tracking and status reporting
    - Integration with SelfOptimizer for performance tracking
    """

    def __init__(self, tool_executor: Optional[Callable] = None) -> None:
        self._plans: Dict[str, TaskPlan] = {}
        self._tool_executor = tool_executor

    def create_plan(self, goal: str, tasks: List[Dict[str, Any]]) -> TaskPlan:
        """Build a plan from a list of task definitions.

        Each task dict can include:
            title, description, tool_name, tool_params, depends_on (list of task IDs)
        """
        subtasks = []
        for spec in tasks:
            subtask = SubTask(
                id=spec.get("id", uuid.uuid4().hex[:8]),
                title=spec.get("title", "Untitled Task"),
                description=spec.get("description", ""),
                tool_name=spec.get("tool_name"),
                tool_params=spec.get("tool_params", {}),
                depends_on=spec.get("depends_on", []),
                max_retries=spec.get("max_retries", 2),
            )
            subtasks.append(subtask)

        plan = TaskPlan(goal=goal, tasks=subtasks)
        self._plans[plan.id] = plan
        logger.info(
            "Created plan '%s' with %d tasks for goal: %s", plan.id, len(subtasks), goal
        )
        return plan

    def get_ready_tasks(self, plan: TaskPlan) -> List[SubTask]:
        """Find all tasks whose dependencies are satisfied and are ready to run."""
        completed_ids: Set[str] = {
            t.id
            for t in plan.tasks
            if t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
        }
        ready = []
        for task in plan.tasks:
            if task.status != TaskStatus.PENDING:
                continue
            deps_met = all(dep_id in completed_ids for dep_id in task.depends_on)
            if deps_met:
                ready.append(task)
        return ready

    def execute_plan(self, plan: TaskPlan) -> TaskPlan:
        """Execute all tasks in dependency order, synchronously."""
        plan.status = TaskStatus.RUNNING
        optimizer = get_optimizer()

        while True:
            ready = self.get_ready_tasks(plan)
            if not ready:
                break

            for task in ready:
                self._execute_task(task, plan, optimizer)

            # Check for deadlocks — remaining pending tasks with unmet deps
            pending = [t for t in plan.tasks if t.status == TaskStatus.PENDING]
            if pending and not ready:
                for t in pending:
                    t.status = TaskStatus.BLOCKED
                    t.error = "Blocked by failed or missing dependency"
                break

        all_done = all(
            t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED, TaskStatus.BLOCKED)
            for t in plan.tasks
        )
        failed_count = sum(1 for t in plan.tasks if t.status == TaskStatus.FAILED)

        if all_done and failed_count == 0:
            plan.status = TaskStatus.COMPLETED
        elif failed_count > 0:
            plan.status = TaskStatus.FAILED
        plan.completed_at = time.time()

        _emit_task_event(plan.id, {
            "type": "plan_complete",
            "plan_id": plan.id,
            "status": plan.status.value,
            "progress": plan.progress,
        })

        optimizer.record(
            component="task_planner",
            action="execute_plan",
            duration_ms=(plan.completed_at - plan.created_at) * 1000,
            success=plan.status == TaskStatus.COMPLETED,
            metadata={"plan_id": plan.id, "total_tasks": len(plan.tasks)},
        )

        return plan

    def _execute_task(self, task: SubTask, plan: TaskPlan, optimizer: Any) -> None:
        """Execute a single subtask with retry logic."""
        task.status = TaskStatus.RUNNING
        _emit_task_event(plan.id, {
            "type": "task_update",
            "plan_id": plan.id,
            "task_id": task.id,
            "title": task.title,
            "status": task.status.value,
            "tool_name": task.tool_name,
            "retries": task.retries,
            "duration_ms": task.duration_ms,
        })
        logger.info("Executing task [%s]: %s", task.id, task.title)

        for attempt in range(task.max_retries + 1):
            start = time.perf_counter()
            try:
                if task.tool_name and self._tool_executor:
                    result = self._tool_executor(task.tool_name, task.tool_params)
                    task.result = result
                    success = (
                        getattr(result, "success", True)
                        if hasattr(result, "success")
                        else True
                    )
                else:
                    task.result = {
                        "message": f"Task '{task.title}' marked complete (no tool assigned)"
                    }
                    success = True

                task.duration_ms = (time.perf_counter() - start) * 1000
                task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED

                if success:
                    _emit_task_event(plan.id, {
                        "type": "task_update",
                        "plan_id": plan.id,
                        "task_id": task.id,
                        "title": task.title,
                        "status": task.status.value,
                        "tool_name": task.tool_name,
                        "retries": task.retries,
                        "duration_ms": task.duration_ms,
                    })
                    optimizer.record(
                        component=f"task:{task.tool_name or 'manual'}",
                        action=task.title,
                        duration_ms=task.duration_ms,
                        success=True,
                    )
                    return

                if not success and attempt < task.max_retries:
                    task.retries += 1
                    time.sleep(0.5 * (attempt + 1))
                    continue

            except Exception as exc:
                task.duration_ms = (time.perf_counter() - start) * 1000
                task.error = str(exc)
                task.retries = attempt
                logger.warning(
                    "Task [%s] attempt %d failed: %s", task.id, attempt + 1, exc
                )

                if attempt < task.max_retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue

                task.status = TaskStatus.FAILED
                _emit_task_event(plan.id, {
                    "type": "task_update",
                    "plan_id": plan.id,
                    "task_id": task.id,
                    "title": task.title,
                    "status": task.status.value,
                    "tool_name": task.tool_name,
                    "retries": task.retries,
                    "duration_ms": task.duration_ms,
                })
                optimizer.record(
                    component=f"task:{task.tool_name or 'manual'}",
                    action=task.title,
                    duration_ms=task.duration_ms,
                    success=False,
                    error=str(exc),
                )
                return

        task.status = TaskStatus.FAILED
        _emit_task_event(plan.id, {
            "type": "task_update",
            "plan_id": plan.id,
            "task_id": task.id,
            "title": task.title,
            "status": task.status.value,
            "tool_name": task.tool_name,
            "retries": task.retries,
            "duration_ms": task.duration_ms,
        })

    def get_plan(self, plan_id: str) -> Optional[TaskPlan]:
        return self._plans.get(plan_id)

    def list_plans(self) -> List[Dict[str, Any]]:
        return [plan.summary for plan in self._plans.values()]

    def get_all_plans(self) -> list:
        """Return all plans with their current status summaries."""
        return [plan.summary for plan in self._plans.values()]

    def get_plan_detail(self, plan_id: str) -> Optional[dict]:
        """Return full plan detail including all subtask statuses."""
        plan = self._plans.get(plan_id)
        if not plan:
            return None
        return {
            "plan_id": plan.id,
            "goal": plan.goal,
            "status": plan.status.value,
            "progress": plan.progress,
            "created_at": plan.created_at,
            "completed_at": plan.completed_at,
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "description": t.description,
                    "tool_name": t.tool_name,
                    "status": t.status.value,
                    "depends_on": t.depends_on,
                    "duration_ms": t.duration_ms,
                    "retries": t.retries,
                    "error": t.error,
                }
                for t in plan.tasks
            ],
        }

    def cancel_plan(self, plan_id: str) -> bool:
        """Mark all pending/running tasks as skipped and fail the plan."""
        plan = self._plans.get(plan_id)
        if not plan:
            return False
        for task in plan.tasks:
            if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                task.status = TaskStatus.SKIPPED
                task.error = "Cancelled by user"
        plan.status = TaskStatus.FAILED
        plan.completed_at = time.time()
        _emit_task_event(plan_id, {
            "type": "plan_complete",
            "plan_id": plan_id,
            "status": "cancelled",
            "progress": plan.progress,
        })
        return True


__all__ = ["TaskPlanner", "TaskPlan", "SubTask", "TaskStatus", "subscribe_to_plan", "unsubscribe_from_plan", "_emit_task_event"]
