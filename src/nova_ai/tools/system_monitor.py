"""System Monitor tool — real-time CPU, memory, disk, and process tracking for performance optimization."""

from __future__ import annotations

import logging
import os
import platform
import time
from typing import Any, Dict

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.engine.self_optimizer import track_execution
from nova_ai.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


def _get_system_info() -> Dict[str, Any]:
    """Gather static system information."""
    return {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "architecture": platform.machine(),
        "processor": platform.processor() or "Unknown",
        "python_version": platform.python_version(),
        "hostname": platform.node(),
        "cpu_count_logical": os.cpu_count() or 0,
    }


def _get_resource_usage() -> Dict[str, Any]:
    """Get current CPU, memory, and disk utilization."""
    try:
        import psutil

        cpu_percent = psutil.cpu_percent(interval=0.5)
        cpu_freq = psutil.cpu_freq()
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(os.sep)
        boot_time = psutil.boot_time()
        uptime_hours = round((time.time() - boot_time) / 3600, 1)

        return {
            "cpu": {
                "usage_percent": cpu_percent,
                "frequency_mhz": round(cpu_freq.current, 0) if cpu_freq else 0,
                "cores_logical": psutil.cpu_count(logical=True),
                "cores_physical": psutil.cpu_count(logical=False),
            },
            "memory": {
                "total_gb": round(mem.total / (1024**3), 2),
                "used_gb": round(mem.used / (1024**3), 2),
                "available_gb": round(mem.available / (1024**3), 2),
                "usage_percent": mem.percent,
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "usage_percent": round(disk.used / disk.total * 100, 1),
            },
            "uptime_hours": uptime_hours,
        }

    except ImportError:
        return _get_basic_resource_usage()


def _get_basic_resource_usage() -> Dict[str, Any]:
    """Fallback resource info without psutil."""
    import shutil

    total, used, free = shutil.disk_usage(os.sep)
    return {
        "cpu": {
            "usage_percent": "N/A (install psutil)",
            "cores_logical": os.cpu_count(),
        },
        "memory": {"info": "Install psutil for memory stats: pip install psutil"},
        "disk": {
            "total_gb": round(total / (1024**3), 2),
            "used_gb": round(used / (1024**3), 2),
            "free_gb": round(free / (1024**3), 2),
            "usage_percent": round(used / total * 100, 1),
        },
    }


def _get_top_processes(limit: int = 10) -> list:
    """Get top processes by memory usage."""
    try:
        import psutil

        procs = []
        for proc in psutil.process_iter(
            ["pid", "name", "memory_percent", "cpu_percent", "status"]
        ):
            try:
                info = proc.info
                if info["memory_percent"] and info["memory_percent"] > 0.1:
                    procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        procs.sort(key=lambda p: p.get("memory_percent", 0), reverse=True)
        return procs[:limit]

    except ImportError:
        return []


def _format_report(
    system: Dict[str, Any],
    resources: Dict[str, Any],
    processes: list,
    include_processes: bool,
) -> str:
    """Format system metrics into a readable report."""
    lines = [
        "## System Performance Report",
        "",
        "### System Info",
        f"  - **OS:** {system['platform']} {system['platform_release']}",
        f"  - **Architecture:** {system['architecture']}",
        f"  - **CPU Cores:** {system['cpu_count_logical']}",
        f"  - **Python:** {system['python_version']}",
        "",
        "### Resource Usage",
    ]

    cpu = resources.get("cpu", {})
    mem = resources.get("memory", {})
    disk = resources.get("disk", {})

    if isinstance(cpu.get("usage_percent"), (int, float)):
        bar_len = int(cpu["usage_percent"] / 5)
        cpu_bar = "█" * bar_len + "░" * (20 - bar_len)
        lines.append(f"  - **CPU:** [{cpu_bar}] {cpu['usage_percent']}%")
    else:
        lines.append(f"  - **CPU:** {cpu.get('usage_percent', 'N/A')}")

    if "usage_percent" in mem:
        bar_len = int(mem["usage_percent"] / 5)
        mem_bar = "█" * bar_len + "░" * (20 - bar_len)
        lines.append(
            f"  - **RAM:** [{mem_bar}] {mem['usage_percent']}% ({mem.get('used_gb', '?')}/{mem.get('total_gb', '?')} GB)"
        )
    elif "info" in mem:
        lines.append(f"  - **RAM:** {mem['info']}")

    disk_pct = disk.get("usage_percent", 0)
    bar_len = int(disk_pct / 5)
    disk_bar = "█" * bar_len + "░" * (20 - bar_len)
    lines.append(
        f"  - **Disk:** [{disk_bar}] {disk_pct}% ({disk.get('used_gb', '?')}/{disk.get('total_gb', '?')} GB)"
    )

    if resources.get("uptime_hours"):
        lines.append(f"  - **Uptime:** {resources['uptime_hours']} hours")

    # Health assessment
    lines.append("")
    lines.append("### Health Assessment")
    warnings = []
    if isinstance(cpu.get("usage_percent"), (int, float)) and cpu["usage_percent"] > 85:
        warnings.append("⚠️ CPU usage is high — consider closing unused applications")
    if "usage_percent" in mem and mem["usage_percent"] > 85:
        warnings.append("⚠️ Memory usage is high — consider freeing RAM")
    if disk_pct > 90:
        warnings.append("⚠️ Disk space is low — clean up temporary files")

    if warnings:
        for w in warnings:
            lines.append(f"  - {w}")
    else:
        lines.append("  - ✅ All resources within healthy thresholds")

    # Top processes
    if include_processes and processes:
        lines.append("")
        lines.append("### Top Processes (by Memory)")
        lines.append("| PID | Name | Memory % | CPU % | Status |")
        lines.append("|-----|------|----------|-------|--------|")
        for p in processes:
            lines.append(
                f"| {p.get('pid', '')} | {p.get('name', '')[:25]} | "
                f"{p.get('memory_percent', 0):.1f}% | {p.get('cpu_percent', 0):.1f}% | "
                f"{p.get('status', '')} |"
            )

    return "\n".join(lines)


@ToolRegistry.register("system_monitor")
class SystemMonitorTool(BaseTool):
    """Monitor system resources: CPU, RAM, disk usage, and running processes."""

    tool_id = "system_monitor"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="system_monitor",
            description=(
                "Monitor system performance: CPU usage, memory consumption, disk space, "
                "uptime, and top processes. Provides health assessments and optimization tips."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "include_processes": {
                        "type": "boolean",
                        "description": "Include top processes by memory usage.",
                        "default": False,
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "Number of top processes to show.",
                        "default": 10,
                    },
                },
            },
            category="system",
            timeout_seconds=10.0,
        )

    @track_execution("system_monitor")
    def execute(
        self,
        include_processes: bool = False,
        top_n: int = 10,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            system = _get_system_info()
            resources = _get_resource_usage()
            processes = _get_top_processes(top_n) if include_processes else []

            report = _format_report(system, resources, processes, include_processes)

            return ToolResult(
                tool_name="system_monitor",
                content=report,
                success=True,
                metadata={
                    "cpu_percent": resources.get("cpu", {}).get("usage_percent"),
                    "memory_percent": resources.get("memory", {}).get("usage_percent"),
                    "disk_percent": resources.get("disk", {}).get("usage_percent"),
                },
            )
        except Exception as e:
            return ToolResult(
                tool_name="system_monitor",
                content=f"Monitoring failed: {e}",
                success=False,
            )


__all__ = ["SystemMonitorTool"]
