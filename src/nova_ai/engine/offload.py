"""Hardware inspector & dynamic offloading calculator.

Measures live GPU VRAM and system RAM, then auto-computes optimal
``n_gpu_layers`` and ``n_ctx`` for llama.cpp-family engines so models
mount without OOM crashes. Zero-guess defaults: everything is derived
from what the machine can actually hold right now.

Usage::

    from nova_ai.engine.offload import HardwareInspector, OffloadPlan

    inspector = HardwareInspector()
    plan = inspector.plan_offload(
        model_size_gb=4.7,        # file size on disk
        context_length=8192,      # desired context
    )
    plan.n_gpu_layers   # e.g. 28  (or 0 on CPU-only machines)
    plan.n_ctx          # e.g. 8192 (reduced if VRAM can't hold it)
    plan.kv_cache_gb    # estimated KV cache footprint at n_ctx
"""

from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass
from typing import Optional

from nova_ai.core.utils import soft_fail

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Live measurements
# ---------------------------------------------------------------------------


@dataclass
class MemorySnapshot:
    """What the machine can actually dedicate to inference right now."""

    gpu_total_gb: float = 0.0
    gpu_free_gb: float = 0.0
    gpu_vendor: str = ""  # nvidia | amd | apple | ""
    gpu_name: str = ""
    ram_total_gb: float = 0.0
    ram_free_gb: float = 0.0
    cpu_count: int = 0
    apple_unified: bool = False  # Apple Silicon shares RAM/VRAM

    @property
    def vram_usable_gb(self) -> float:
        """VRAM we allow the model to occupy (90% headroom, less on Windows)."""
        if self.gpu_free_gb <= 0:
            return 0.0
        factor = 0.80 if platform.system() == "Windows" else 0.90
        return max(0.0, self.gpu_free_gb * factor)

    @property
    def ram_usable_gb(self) -> float:
        """RAM we allow CPU-side inference to occupy (leave 2 GB for the OS)."""
        if self.ram_free_gb <= 0:
            return 0.0
        return max(0.0, self.ram_free_gb - 2.0)


class HardwareInspector:
    """Reads live memory/VRAM figures with layered fallbacks."""

    def snapshot(self) -> MemorySnapshot:
        snap = MemorySnapshot(cpu_count=os.cpu_count() or 1)
        self._fill_ram(snap)
        self._fill_nvidia(snap)
        if snap.gpu_vendor == "":
            self._fill_amd(snap)
        if snap.gpu_vendor == "" and platform.system() == "Darwin":
            self._fill_apple(snap)
        if snap.gpu_vendor == "":
            # iGPU fallback (Intel/AMD integrated): WMI on Windows reports
            # adapter RAM; usable VRAM is typically half of shared memory.
            self._fill_integrated(snap)
        return snap

    # -- RAM ------------------------------------------------------------------

    def _fill_ram(self, snap: MemorySnapshot) -> None:
        # psutil when available (free RAM, not just total)
        try:
            import psutil  # type: ignore[import-untyped]

            vm = psutil.virtual_memory()
            snap.ram_total_gb = round(vm.total / 1024**3, 2)
            snap.ram_free_gb = round(vm.available / 1024**3, 2)
            return
        except ImportError:
            pass

        # stdlib fallbacks
        system = platform.system()
        try:
            if system == "Windows":
                import ctypes

                class _MemStatus(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                st = _MemStatus()
                st.dwLength = ctypes.sizeof(_MemStatus)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                    snap.ram_total_gb = round(st.ullTotalPhys / 1024**3, 2)
                    snap.ram_free_gb = round(st.ullAvailPhys / 1024**3, 2)
            elif system == "Linux":
                info = {}
                for line in open("/proc/meminfo").read().splitlines():  # noqa: SIM115
                    key, _, val = line.partition(":")
                    info[key.strip()] = val.strip().split()[0]
                snap.ram_total_gb = round(int(info["MemTotal"]) / 1024**2, 2)
                snap.ram_free_gb = round(int(info["MemAvailable"]) / 1024**2, 2)
            elif system == "Darwin":
                import subprocess

                total = subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                ).stdout.strip()
                snap.ram_total_gb = round(int(total) / 1024**3, 2)
                snap.ram_free_gb = snap.ram_total_gb * 0.6  # heuristic
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            logger.debug("RAM probe failed; totals stay 0", exc_info=True)

    # -- GPUs -------------------------------------------------------------------

    def _fill_nvidia(self, snap: MemorySnapshot) -> None:
        # pynvml is precise (free vs total VRAM)
        try:
            import pynvml  # type: ignore[import-untyped]

            pynvml.nvmlInit()
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                name = pynvml.nvmlDeviceGetName(handle)
                snap.gpu_vendor = "nvidia"
                snap.gpu_name = name.decode() if isinstance(name, bytes) else str(name)
                snap.gpu_total_gb = round(mem.total / 1024**3, 2)
                snap.gpu_free_gb = round(mem.free / 1024**3, 2)
            finally:
                pynvml.nvmlShutdown()
            return
        except Exception as exc:  # noqa: BLE001 — fall through to nvidia-smi
            soft_fail(logger, exc, "optional engine capability")

        # nvidia-smi CLI fallback (PATH first, then standard install dirs)
        import shutil
        import subprocess

        smi = shutil.which("nvidia-smi")
        if not smi:
            for candidate in (
                r"C:\Windows\System32\nvidia-smi.exe",
                r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
            ):
                if os.path.isfile(candidate):
                    smi = candidate
                    break
        if not smi:
            return
        try:
            raw = subprocess.run(
                [
                    smi,
                    "--query-gpu=name,memory.total,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            first = raw.splitlines()[0]
            parts = [p.strip() for p in first.split(",")]
            snap.gpu_vendor = "nvidia"
            snap.gpu_name = parts[0]
            snap.gpu_total_gb = round(float(parts[1]) / 1024, 2)
            snap.gpu_free_gb = round(float(parts[2]) / 1024, 2)
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            pass

    def _fill_amd(self, snap: MemorySnapshot) -> None:
        import shutil
        import subprocess

        if not shutil.which("rocm-smi"):
            return
        try:
            raw = subprocess.run(
                ["rocm-smi", "--showmeminfo", "vram", "--csv"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            for line in raw.splitlines():
                low = line.lower()
                if "total" in low and ("vram" in low or "memory" in low):
                    for token in line.replace(",", " ").split():
                        if token.isdigit():
                            gb = round(int(token) / 1024**3, 2)
                            if gb > 0.5:
                                snap.gpu_vendor = "amd"
                                snap.gpu_name = "AMD GPU"
                                snap.gpu_total_gb = gb
                                snap.gpu_free_gb = gb * 0.85
                                return
        except (OSError, ValueError, subprocess.SubprocessError):
            pass

    def _fill_apple(self, snap: MemorySnapshot) -> None:
        snap.gpu_vendor = "apple"
        snap.gpu_name = f"Apple {platform.machine()}"
        snap.apple_unified = True
        # Metal-style unified memory: GPU may use ~65-75% of RAM
        snap.gpu_total_gb = round(snap.ram_total_gb * 0.70, 2)
        snap.gpu_free_gb = round(snap.ram_free_gb * 0.70, 2)

    def _fill_integrated(self, snap: MemorySnapshot) -> None:
        """Integrated GPU fallback — Windows WMI adapter RAM, else none.

        iGPUs share system RAM with no dedicated VRAM, so we expose a
        conservative slice (25% of free RAM) as "usable VRAM" — llama.cpp
        with a Vulkan/SYCL/OpenCL backend can offload into shared memory.
        """
        if platform.system() != "Windows":
            return
        try:
            import subprocess

            ps = (
                "Get-CimInstance Win32_VideoController | "
                "Select-Object -First 1 -ExpandProperty Name"
            )
            name = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            if not name:
                return
            ps_ram = (
                "Get-CimInstance Win32_VideoController | "
                "Select-Object -First 1 -ExpandProperty AdapterRAM"
            )
            raw = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_ram],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            adapter_bytes = int(raw) if raw.isdigit() else 0
            # AdapterRAM is uint32-capped at 4 GB and reports shared
            # allocation; cap our claim to 25% of free RAM.
            shared_gb = min(adapter_bytes / 1024**3, snap.ram_free_gb)
            claimed = round(min(shared_gb * 0.5, snap.ram_free_gb * 0.25), 2)
            if claimed >= 0.5:
                snap.gpu_vendor = "integrated"
                snap.gpu_name = name
                snap.gpu_total_gb = claimed
                snap.gpu_free_gb = claimed
        except (OSError, ValueError, subprocess.SubprocessError):
            pass


# ---------------------------------------------------------------------------
# Offload planner
# ---------------------------------------------------------------------------

# Bytes/parameter at common quant levels (GGUF K-Quants), incl. ~8% overhead
_QUANT_BYTES_PER_PARAM = {
    "q2_k": 0.30,
    "q3_k_m": 0.42,
    "q4_0": 0.52,
    "q4_k_m": 0.58,
    "q5_k_m": 0.70,
    "q6_k": 0.82,
    "q8_0": 1.07,
    "f16": 2.05,
}

# KV cache bytes per token per billion params ≈ 2 (K+V) * n_layers * n_kv_heads
# * head_dim * dtype. Worst case (legacy MHA, fp16, ~32L/32H/128d per 7B) works
# out to ~75,000 bytes/token/B; modern GQA models (llama3/mistral/qwen) are
# 4-8x smaller still. The old 170,000 overestimated by 2.3x+ even for MHA and
# shrank context far more aggressively than needed.
_KV_BYTES_PER_TOKEN_PER_B_PARAMS = 75_000  # worst-case MHA @ fp16; GQA is smaller


@dataclass
class OffloadPlan:
    """Resolved launch parameters for a llama.cpp-style engine."""

    n_gpu_layers: int = 0  # 0 = CPU only; -1 = full offload
    n_ctx: int = 4096
    n_threads: int = 0  # 0 = llama.cpp default
    offload_pct: int = 0  # estimated % of weights on GPU
    kv_cache_gb: float = 0.0
    vram_estimate_gb: float = 0.0
    fits_gpu: bool = False
    device: str = "cpu"  # cpu | gpu | hybrid
    notes: str = ""

    def to_llama_kwargs(self) -> dict:
        """Ready-to-spread kwargs for ``llama_cpp.Llama(...)``."""
        return {
            "n_gpu_layers": self.n_gpu_layers,
            "n_ctx": self.n_ctx,
            "n_threads": self.n_threads or None,
        }


class OffloadPlanner:
    """Computes n_gpu_layers / n_ctx from a live :class:`MemorySnapshot`."""

    def __init__(self, snapshot: Optional[MemorySnapshot] = None) -> None:
        self.snap = snapshot or HardwareInspector().snapshot()

    # -- model math -----------------------------------------------------------

    @staticmethod
    def _quant_from_filename(name: str) -> float:
        low = name.lower()
        for key, bpp in _QUANT_BYTES_PER_PARAM.items():
            if key in low:
                return bpp
        if ".gguf" in low:
            return 0.58  # assume Q4_K_M
        return 2.05  # fp16 safetensors

    def _param_count(self, model_size_gb: float, quant_bpp: float) -> float:
        """Estimated parameter count (in billions) from file size + quant."""
        return model_size_gb / quant_bpp if quant_bpp > 0 else 0.0

    def _kv_cache_gb(self, params_b: float, ctx: int) -> float:
        """Estimated KV cache at ``ctx`` tokens."""
        return (params_b * _KV_BYTES_PER_TOKEN_PER_B_PARAMS * ctx) / 1024**3

    # -- planning ---------------------------------------------------------------

    def plan(
        self,
        model_size_gb: float,
        context_length: int = 4096,
        filename: str = "",
        *,
        min_ctx: int = 1024,
        max_ctx: int = 32768,
    ) -> OffloadPlan:
        """Derive a zero-OOM offload plan for the target model."""
        quant_bpp = self._quant_from_filename(filename or "")
        params_b = self._param_count(model_size_gb, quant_bpp)

        vram = self.snap.vram_usable_gb
        ram = self.snap.ram_usable_gb
        apple = self.snap.apple_unified

        # ---- n_gpu_layers -----------------------------------------------------
        if vram >= model_size_gb * 1.15:
            # Whole model + activations + KV fit comfortably
            plan_gpu_layers = -1
            offload_pct = 100
        elif vram > 0:
            # Partial offload: layers proportional to VRAM share.
            # KV cache lives on GPU when offloading, reserve 20% for it.
            usable_for_weights = vram * 0.80
            share = max(0.0, min(1.0, usable_for_weights / max(model_size_gb, 0.01)))
            offload_pct = int(share * 100)
            # llama.cpp takes layers, not bytes: approximate linear mapping
            plan_gpu_layers = max(0, int(round(share * 32)))  # 32-layer proxy
        else:
            plan_gpu_layers = 0
            offload_pct = 0

        # ---- n_ctx --------------------------------------------------------------
        # Shrink context until KV cache + weights fit in the chosen device pool.
        # Hybrid builds draw on VRAM *and* system RAM (CPU-resident layers +
        # mmap page cache), so the pool is the sum of both. The fit check uses
        # the WHOLE model (all weights + KV), not just the GPU-resident share —
        # CPU layers still consume real RAM.
        pool_gb = vram + ram * (0.6 if apple else 1.0) if vram > 0 else ram
        ctx = max(min_ctx, min(context_length, max_ctx))
        kv = self._kv_cache_gb(params_b, ctx)
        if plan_gpu_layers > 0:
            offload_pct = max(
                offload_pct, int(100 * min(1.0, vram / max(model_size_gb, 0.01)))
            )

        while ctx > min_ctx:
            if model_size_gb + kv <= pool_gb:
                break
            ctx = max(min_ctx, int(ctx * 0.75))
            kv = self._kv_cache_gb(params_b, ctx)

        fits = model_size_gb + kv <= pool_gb if pool_gb > 0 else False
        footprint_gb = model_size_gb + kv
        device = (
            "gpu"
            if plan_gpu_layers == -1
            else "hybrid"
            if plan_gpu_layers > 0
            else "cpu"
        )

        notes_parts = []
        if ctx < context_length:
            notes_parts.append(f"context reduced {context_length}→{ctx} to avoid OOM")
        if plan_gpu_layers not in (-1, 0) and offload_pct:
            notes_parts.append(f"partial offload ~{offload_pct}% of weights to GPU")
        if plan_gpu_layers == 0:
            notes_parts.append("CPU-only: no usable VRAM detected")
        if not fits:
            notes_parts.append(
                f"WARNING: model may not fit (need ~{footprint_gb:.1f} GB, "
                f"have ~{pool_gb:.1f} GB)"
            )

        n_threads = 0
        if device == "cpu" or plan_gpu_layers == 0:
            # Physical cores ≈ half of logical on hyperthreaded machines
            n_threads = max(1, (self.snap.cpu_count or 4) // 2)

        return OffloadPlan(
            n_gpu_layers=plan_gpu_layers,
            n_ctx=ctx,
            n_threads=n_threads,
            offload_pct=offload_pct,
            kv_cache_gb=round(kv, 2),
            vram_estimate_gb=round(footprint_gb, 2),
            fits_gpu=fits,
            device=device,
            notes="; ".join(notes_parts),
        )


def recommend_catalog_model(
    catalog: list[dict], snapshot: Optional[MemorySnapshot] = None
) -> list[dict]:
    """Annotate a GGUF-style catalog with ``will_fit`` per entry.

    Each entry needs ``size_gb``; adds ``fit`` = True/False/"partial"
    plus a human hint the UI can surface.
    """
    planner = OffloadPlanner(snapshot)
    vram = planner.snap.vram_usable_gb
    ram = planner.snap.ram_usable_gb
    pool = vram + ram * (0.6 if planner.snap.apple_unified else 1.0)

    out = []
    for entry in catalog:
        size = float(entry.get("size_gb", 0) or 0)
        if size <= 0:
            fit, hint = None, ""
        elif vram >= size * 1.15:
            fit, hint = True, f"GPU-accelerated (~{size:.1f} GB VRAM)"
        elif pool >= size * 1.15:
            fit = "partial"
            hint = (
                f"Hybrid: ~{int((vram / size) * 100)}% offloaded to GPU"
                if vram > 0
                else "CPU inference (RAM only)"
            )
        elif pool >= size:
            fit, hint = "partial", "Tight fit — reduced context recommended"
        else:
            fit, hint = (
                False,
                f"Needs ~{size:.1f} GB; this machine has ~{pool:.1f} GB usable",
            )
        out.append({**entry, "fit": fit, "fit_hint": hint})
    return out
