"""Benchmarking framework for NOVA AI inference engines."""

from __future__ import annotations

from nova_ai.bench._stubs import BaseBenchmark, BenchmarkResult, BenchmarkSuite
from nova_ai.core.registry import BenchmarkRegistry


def ensure_registered() -> None:
    """Ensure all benchmark implementations are registered."""
    from nova_ai.bench.energy import ensure_registered as _reg_energy
    from nova_ai.bench.latency import ensure_registered as _reg_latency
    from nova_ai.bench.throughput import ensure_registered as _reg_throughput

    _reg_latency()
    _reg_throughput()
    _reg_energy()


# Trigger registration on import
ensure_registered()

__all__ = [
    "BaseBenchmark",
    "BenchmarkRegistry",
    "BenchmarkResult",
    "BenchmarkSuite",
    "ensure_registered",
]
