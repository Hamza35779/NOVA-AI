"""Default-model recommendation.

Split out of the original monolithic ``core/config.py``. Re-exported by the
``nova_ai.core.config`` facade.
"""

from __future__ import annotations

from nova_ai.core.config.hardware import HardwareInfo, _available_memory_gb

# Explicit tier table: (max_ram_gb, model_id).
# Walked in order — first tier where available_gb <= max_ram is chosen.
# Uses Qwen3.5 MoE models — better quality per GB than dense models since
# only a fraction of parameters are active per token.
_MODEL_TIERS = [
    (8, "qwen3.5:2b"),
    (16, "qwen3.5:4b"),
    (32, "qwen3.5:9b"),
    (64, "qwen3.5:27b"),
]
_MODEL_TIER_FALLBACK = "qwen3.5:27b"
_LEMONADE_DEFAULT_MODEL = "Qwen3.6-35B-A3B-GGUF"


def recommend_model(hw: HardwareInfo, engine: str) -> str:
    """Suggest a default model for the selected engine and hardware.

    For Lemonade, prefer the validated Qwen3.6 35B A3B GGUF default.
    For other local engines, use the generic Qwen3.5 tier mapping.
    """
    from nova_ai.intelligence.model_catalog import BUILTIN_MODELS

    available_gb = _available_memory_gb(hw)
    if available_gb <= 0:
        return ""

    if engine == "lemonade":
        return _LEMONADE_DEFAULT_MODEL

    # Build a lookup for quick engine-compatibility checks
    catalog = {spec.model_id: spec for spec in BUILTIN_MODELS}

    # Try explicit tier mapping first
    model_id = _MODEL_TIER_FALLBACK
    for max_ram, tier_model in _MODEL_TIERS:
        if available_gb <= max_ram:
            model_id = tier_model
            break

    spec = catalog.get(model_id)
    if spec and engine in spec.supported_engines:
        return model_id

    # Fallback: scan all Qwen3.5 models for engine compatibility
    candidates = [
        s
        for s in BUILTIN_MODELS
        if s.provider == "alibaba"
        and s.model_id.startswith("qwen3.5:")
        and engine in s.supported_engines
    ]
    candidates.sort(key=lambda s: s.parameter_count_b, reverse=True)
    for s in candidates:
        estimated_gb = s.parameter_count_b * 0.5 * 1.1
        if estimated_gb <= available_gb:
            return s.model_id

    return ""


def estimated_download_gb(parameter_count_b: float) -> float:
    """Estimate download size in GB for Q4_K_M quantized model."""
    return parameter_count_b * 0.5 * 1.1

