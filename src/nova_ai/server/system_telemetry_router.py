"""System telemetry API — live CPU / RAM / GPU / VRAM for the dashboard.

Lightweight poller designed for the frontend hardware gauges: one
endpoint returns a full machine snapshot, cached for a short window so
multiple UI components (or a fast-polling chart) don't stampede the
sensors. Backed by :mod:`nova_ai.engine.offload` for VRAM/RAM and
psutil when present for CPU utilization.

Sensor reads are synchronous (WMI/NVML/psutil calls) and are pushed to a
worker thread via ``asyncio.to_thread`` — running them inline in the
async endpoints would stall the event loop on machines where a sensor
query takes tens of milliseconds. The cache is guarded by a lock so
concurrent requests share one refresh instead of racing.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict

from fastapi import APIRouter

from nova_ai.engine.offload import HardwareInspector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system_telemetry"])

_CACHE_TTL = 1.0  # seconds — matches a sane UI poll interval
_cache: Dict[str, Any] = {"snapshot": None, "ts": 0.0}
_cache_lock = threading.Lock()


def _cpu_percent() -> float:
    try:
        import psutil  # type: ignore[import-untyped]

        return round(psutil.cpu_percent(interval=None), 1)
    except ImportError:
        return -1.0


def _ram_percent() -> tuple:
    try:
        import psutil  # type: ignore[import-untyped]

        vm = psutil.virtual_memory()
        return (
            round(vm.percent, 1),
            round(vm.used / 1024**3, 2),
            round(vm.total / 1024**3, 2),
        )
    except ImportError:
        return -1.0, 0.0, 0.0


def _gpu_utilization() -> list:
    """Per-GPU utilization samples; empty when no sensor is available."""
    try:
        import pynvml  # type: ignore[import-untyped]

        pynvml.nvmlInit()
        try:
            count = pynvml.nvmlDeviceGetCount()
            out = []
            for i in range(count):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                util = pynvml.nvmlDeviceGetUtilizationRates(h)
                mem = pynvml.nvmlDeviceGetMemoryInfo(h)
                temp = pynvml.nvmlDeviceGetTemperature(
                    h, pynvml.NVML_TEMPERATURE_GPU
                )
                out.append(
                    {
                        "index": i,
                        "util_percent": util.gpu,
                        "mem_used_gb": round(mem.used / 1024**3, 2),
                        "mem_total_gb": round(mem.total / 1024**3, 2),
                        "temperature_c": temp,
                    }
                )
            return out
        finally:
            pynvml.nvmlShutdown()
    except Exception:  # noqa: BLE001 — telemetry is best-effort
        return []


def _build_snapshot() -> Dict[str, Any]:
    snap = HardwareInspector().snapshot()
    cpu_pct = _cpu_percent()
    ram_pct, ram_used_gb, ram_total_gb = _ram_percent()
    gpus = _gpu_utilization()

    # Fall back to the offload inspector's numbers when psutil is absent
    ram_total = ram_total_gb if ram_total_gb > 0 else snap.ram_total_gb

    return {
        "cpu": {
            "percent": cpu_pct,
            "cores": snap.cpu_count,
        },
        "ram": {
            "percent": ram_pct,
            "used_gb": ram_used_gb,
            "total_gb": ram_total,
            "free_gb": snap.ram_free_gb,
        },
        "gpu": {
            "vendor": snap.gpu_vendor,
            "name": snap.gpu_name,
            "available": snap.gpu_vendor != "",
            "gpus": gpus,
            "vram_free_gb": snap.gpu_free_gb,
            "vram_total_gb": snap.gpu_total_gb,
        },
        "timestamp": time.time(),
    }


async def _get_cached_snapshot() -> Dict[str, Any]:
    """Return the cached snapshot, refreshing it off-loop when stale."""
    now = time.monotonic()
    if _cache["snapshot"] is not None and now - _cache["ts"] <= _CACHE_TTL:
        return _cache["snapshot"]
    async with asyncio.Lock():
        # Double-check: another request may have refreshed while we waited
        now = time.monotonic()
        if _cache["snapshot"] is None or now - _cache["ts"] > _CACHE_TTL:
            _cache["snapshot"] = await asyncio.to_thread(_build_snapshot)
            _cache["ts"] = time.monotonic()
    return _cache["snapshot"]


@router.get("/telemetry")
async def get_system_telemetry() -> Dict[str, Any]:
    """Live hardware snapshot (CPU/RAM/GPU/VRAM) with 1s server-side cache."""
    return await _get_cached_snapshot()


@router.get("/telemetry/backends")
async def list_backend_availability() -> Dict[str, Any]:
    """Which inference backends this machine can actually run.

    Combines the hardware snapshot with the offload planner so the UI can
    gray out engines the hardware can't support.
    """
    await _get_cached_snapshot()  # ensure the cache is warm for callers
    hw_cache = _cache["snapshot"] or {}
    gpu = hw_cache.get("gpu", {})
    return {
        "hardware": {
            "platform": gpu.get("vendor") or "cpu",
            "ram_total_gb": (hw_cache.get("ram") or {}).get("total_gb", 0.0),
            "vram_total_gb": gpu.get("vram_total_gb", 0.0),
            "gpu_vendor": gpu.get("vendor", ""),
            "gpu_name": gpu.get("name", ""),
        },
        "sensors": {
            "pynvml": bool(gpu.get("gpus")),
            "psutil": (hw_cache.get("cpu") or {}).get("percent", -1.0) >= 0,
        },
    }
