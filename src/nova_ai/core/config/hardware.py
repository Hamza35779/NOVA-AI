"""Hardware detection: GPU/CPU/RAM discovery and engine recommendation.

Split out of the original monolithic ``core/config.py``. Re-exported by the
``nova_ai.core.config`` facade so ``from nova_ai.core.config import
HardwareInfo`` keeps working.
"""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path

from nova_ai.core.paths import get_config_dir, get_config_path


# Patchability shim: tests patch ``nova_ai.core.config.shutil.which`` /
# ``nova_ai.core.config.platform.system`` / ``nova_ai.core.config._run_cmd``.
# To keep those string targets working after the split, the helpers below
# resolve these names through the facade package at call time.
def _facade():
    import nova_ai.core.config as _cfg
    return _cfg

# Legacy names, kept for the ~45 modules that import them. They are resolved
# once at import via the env-aware resolver in ``nova_ai.core.paths`` (the
# install-script model: ``NOVA_AI_HOME`` / ``XDG_DATA_HOME`` are set before
# the process starts). They are real module attributes — not computed lazily —
# so existing tests can ``monkeypatch.setattr`` them and so dataclass-instance
# defaults stay consistent. Code that must react to a mid-process env change
# (or wants the override regardless of import order) should call
# ``get_config_dir()`` / ``get_config_path()`` directly; the dataclass field
# defaults below already do this via ``default_factory``.
DEFAULT_CONFIG_DIR = get_config_dir()
DEFAULT_CONFIG_PATH = get_config_path()


def _ensure_config_dir() -> Path:
    """Ensure the config directory exists with restrictive permissions."""
    from nova_ai.security.file_utils import secure_mkdir

    return secure_mkdir(get_config_dir())



@dataclass(slots=True)
class GpuInfo:
    """Detected GPU metadata."""

    vendor: str = ""
    name: str = ""
    vram_gb: float = 0.0
    compute_capability: str = ""
    count: int = 0


@dataclass(slots=True)
class HardwareInfo:
    """Detected system hardware."""

    platform: str = ""
    cpu_brand: str = ""
    cpu_count: int = 0
    ram_gb: float = 0.0
    gpu: GpuInfo | None = None


# ---------------------------------------------------------------------------
# Hardware detection helpers
# ---------------------------------------------------------------------------


def _run_cmd(cmd: list[str]) -> str:
    """Delegate to the facade's ``_run_cmd`` when patched; else the real impl.

    The facade re-exports this same function object, so a naive
    ``_facade()._run_cmd(cmd)`` would recurse into itself forever
    (RecursionError on the first real nvidia-smi/sysctl probe). When a test
    (or future caller) patches ``nova_ai.core.config._run_cmd`` by string
    path, the facade attribute becomes a DIFFERENT object and we must honor
    it; unpatched, we run the actual implementation.
    """
    current = _facade()._run_cmd
    if current is not _run_cmd:
        return current(cmd)
    return _run_cmd_impl(cmd)


def _run_cmd_impl(cmd: list[str]) -> str:
    """Run a command and return stripped stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,  # noqa: S603
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""


def _detect_nvidia_gpu() -> GpuInfo | None:
    if not _facade().shutil.which("nvidia-smi"):
        return None
    raw = _run_cmd(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,count,compute_cap",
            "--format=csv,noheader,nounits",
        ]
    )
    if not raw:
        return None
    try:
        first_line = raw.splitlines()[0]
        parts = [p.strip() for p in first_line.split(",")]
        name = parts[0]
        vram_mb = float(parts[1])
        count = int(parts[2])
        compute_capability = parts[3] if len(parts) > 3 else ""
        return GpuInfo(
            vendor="nvidia",
            name=name,
            vram_gb=round(vram_mb / 1024, 1),
            compute_capability=compute_capability,
            count=count,
        )
    except (IndexError, ValueError):
        return None


def _detect_amd_gpu() -> GpuInfo | None:
    if not _facade().shutil.which("rocm-smi"):
        return None
    raw = _run_cmd(["rocm-smi", "--showproductname"])
    if not raw:
        return None
    name = raw.splitlines()[0] if raw else "AMD GPU"

    # Parse VRAM from rocm-smi --showmeminfo vram
    vram_gb = 0.0
    try:
        vram_raw = _run_cmd(["rocm-smi", "--showmeminfo", "vram"])
        for line in vram_raw.splitlines():
            if "Total Memory (B):" in line:
                vram_bytes = int(line.split(":")[-1].strip())
                vram_gb = round(vram_bytes / (1024**3), 1)
                break
    except (ValueError, IndexError):
        vram_gb = 0.0

    # Parse GPU count from rocm-smi --showallinfo
    count = 1
    try:
        allinfo_raw = _run_cmd(["rocm-smi", "--showallinfo"])
        import re

        gpu_ids = set(re.findall(r"GPU\[(\d+)\]", allinfo_raw))
        if gpu_ids:
            count = len(gpu_ids)
    except (ValueError, IndexError):
        count = 1

    return GpuInfo(vendor="amd", name=name, vram_gb=vram_gb, count=count)


def _detect_apple_gpu() -> GpuInfo | None:
    if _facade().platform.system() != "Darwin":
        return None
    raw = _run_cmd(["system_profiler", "SPDisplaysDataType"])
    if "Apple" not in raw:
        return None
    # Rough extraction — "Apple M2 Max" etc.
    ram_gb = _total_ram_gb()
    for line in raw.splitlines():
        line = line.strip()
        if "Chipset Model" in line:
            name = line.split(":")[-1].strip()
            return GpuInfo(vendor="apple", name=name, vram_gb=ram_gb, count=1)
    return GpuInfo(vendor="apple", name="Apple Silicon", vram_gb=ram_gb, count=1)


def _detect_cpu_brand() -> str:
    """Best-effort CPU brand string."""
    if platform.system() == "Darwin":
        brand = _run_cmd(["sysctl", "-n", "machdep.cpu.brand_string"])
        if brand:
            return brand
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        try:
            for line in cpuinfo.read_text().splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or "unknown"


def _total_ram_gb() -> float:
    try:
        if _facade().platform.system() == "Darwin":
            raw = _run_cmd(["sysctl", "-n", "hw.memsize"])
            return round(int(raw) / (1024**3), 1) if raw else 0.0
        if _facade().platform.system() == "Windows":
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
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

            stat = _MemoryStatusEx()
            stat.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return round(stat.ullTotalPhys / (1024**3), 1)
            return 0.0
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            for line in meminfo.read_text().splitlines():
                if line.startswith("MemTotal"):
                    kb = int(line.split()[1])
                    return round(kb / (1024**2), 1)
    except (OSError, ValueError, AttributeError):
        pass
    return 0.0


def detect_hardware() -> HardwareInfo:
    """Auto-detect hardware capabilities with graceful fallbacks."""
    gpu = _detect_nvidia_gpu() or _detect_amd_gpu() or _detect_apple_gpu()
    return HardwareInfo(
        platform=_facade().platform.system().lower(),
        cpu_brand=_detect_cpu_brand(),
        cpu_count=os.cpu_count() or 1,
        ram_gb=_total_ram_gb(),
        gpu=gpu,
    )


# ---------------------------------------------------------------------------
# Engine recommendation
# ---------------------------------------------------------------------------


def recommend_engine(hw: HardwareInfo) -> str:
    """Suggest the best inference engine for the detected hardware."""
    gpu = hw.gpu
    if gpu is None:
        return "llamacpp"
    if gpu.vendor == "apple":
        return "mlx"
    if gpu.vendor == "nvidia":
        # Datacenter cards (A100, H100, L40, etc.) → vllm; consumer → ollama
        datacenter_keywords = ("A100", "H100", "H200", "L40", "A10", "A30")
        if any(kw in gpu.name for kw in datacenter_keywords):
            return "vllm"
        return "ollama"
    if gpu.vendor == "amd":
        # Datacenter cards (MI300, MI325, MI350, MI355) → vllm; consumer → lemonade
        amd_datacenter_keywords = ("MI300", "MI325", "MI350", "MI355")
        if any(kw in gpu.name for kw in amd_datacenter_keywords):
            return "vllm"
        return "lemonade"
    return "llamacpp"


def _available_memory_gb(hw: HardwareInfo) -> float:
    """Return usable memory in GB for model loading."""
    gpu = hw.gpu
    if gpu and gpu.vram_gb > 0:
        return gpu.vram_gb * max(gpu.count, 1) * 0.9
    if hw.ram_gb > 0:
        return (hw.ram_gb - 4) * 0.8
    return 0.0


