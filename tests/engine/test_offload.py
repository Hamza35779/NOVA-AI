"""Tests for the hardware inspector & dynamic offload planner."""

from __future__ import annotations

from nova_ai.engine.offload import (
    HardwareInspector,
    MemorySnapshot,
    OffloadPlanner,
    recommend_catalog_model,
)


def _gpu_rig() -> MemorySnapshot:
    return MemorySnapshot(
        gpu_total_gb=8.0,
        gpu_free_gb=7.2,
        gpu_vendor="nvidia",
        gpu_name="RTX 4070",
        ram_total_gb=32,
        ram_free_gb=20,
        cpu_count=16,
    )


def _cpu_rig() -> MemorySnapshot:
    return MemorySnapshot(ram_total_gb=64, ram_free_gb=50, cpu_count=24)


def test_full_offload_when_model_fits() -> None:
    plan = OffloadPlanner(_gpu_rig()).plan(
        model_size_gb=4.7, context_length=8192, filename="q4_k_m.gguf"
    )
    assert plan.device == "gpu"
    assert plan.n_gpu_layers == -1
    assert plan.fits_gpu is True
    assert plan.n_ctx == 8192  # untouched


def test_partial_offload_for_oversized_model() -> None:
    plan = OffloadPlanner(_gpu_rig()).plan(
        model_size_gb=15, context_length=4096, filename="q4_k_m.gguf"
    )
    assert plan.device == "hybrid"
    assert 0 < plan.n_gpu_layers < 32
    assert 0 < plan.offload_pct < 100
    assert plan.fits_gpu is True  # hybrid pool (VRAM+RAM) absorbs it


def test_context_shrinks_to_fit() -> None:
    plan = OffloadPlanner(_gpu_rig()).plan(
        model_size_gb=25, context_length=16384, filename="q4_k_m.gguf"
    )
    assert plan.n_ctx < 16384
    assert plan.n_ctx >= 1024
    assert "context reduced" in plan.notes


def test_cpu_only_machine_gets_zero_layers() -> None:
    plan = OffloadPlanner(_cpu_rig()).plan(
        model_size_gb=12, context_length=8192, filename="q4_k_m.gguf"
    )
    assert plan.device == "cpu"
    assert plan.n_gpu_layers == 0
    assert plan.n_threads > 0
    assert plan.fits_gpu is True  # 50 GB RAM


def test_cpu_only_rejects_oversized_model() -> None:
    plan = OffloadPlanner(_cpu_rig()).plan(
        model_size_gb=80, context_length=4096, filename="q4_k_m.gguf"
    )
    assert plan.fits_gpu is False
    assert "WARNING" in plan.notes


def test_quant_detected_from_filename() -> None:
    q8 = OffloadPlanner(_gpu_rig()).plan(
        model_size_gb=4.7, context_length=4096, filename="model-q8_0.gguf"
    )
    q4 = OffloadPlanner(_gpu_rig()).plan(
        model_size_gb=4.7, context_length=4096, filename="model-q4_k_m.gguf"
    )
    # Same file size at a denser quant = fewer params = smaller KV cache
    assert q8.kv_cache_gb < q4.kv_cache_gb


def test_to_llama_kwargs() -> None:
    plan = OffloadPlanner(_gpu_rig()).plan(
        model_size_gb=4.0, context_length=4096, filename="q4_k_m.gguf"
    )
    kw = plan.to_llama_kwargs()
    assert {"n_gpu_layers", "n_ctx", "n_threads"} <= set(kw)


def test_apple_unified_memory() -> None:
    snap = MemorySnapshot(
        gpu_vendor="apple",
        gpu_name="Apple M2",
        ram_total_gb=32,
        ram_free_gb=20,
        apple_unified=True,
        cpu_count=10,
    )
    planner = OffloadPlanner(snap)
    # Apple unified memory: GPU may claim 70% of RAM
    planner.snap.gpu_total_gb = round(snap.ram_total_gb * 0.70, 2)
    planner.snap.gpu_free_gb = round(snap.ram_free_gb * 0.70, 2)
    plan = planner.plan(
        model_size_gb=8, context_length=4096, filename="q4_k_m.gguf"
    )
    assert plan.device in ("gpu", "hybrid")
    assert plan.n_gpu_layers != 0


def test_recommend_catalog_annotates_fit() -> None:
    catalog = [
        {"id": "tiny", "size_gb": 0.5},
        {"id": "fits", "size_gb": 4.7},
        {"id": "huge", "size_gb": 40},
    ]
    out = recommend_catalog_model(catalog, _gpu_rig())
    by_id = {c["id"]: c for c in out}
    assert by_id["fits"]["fit"] is True
    assert by_id["huge"]["fit"] is False
    assert by_id["tiny"]["fit"] in (True, "partial")
    assert all("fit_hint" in c for c in out)


def test_inspector_returns_snapshot() -> None:
    snap = HardwareInspector().snapshot()
    assert snap.cpu_count >= 1
    assert isinstance(snap.ram_total_gb, float)
