"""Cloud-model pricing + per-family quirks for hybrid paradigm agents.

Canonical numbers live in ``nova_ai.core.pricing`` (B3 fix). This module
re-exports them for backward compat; the old verbatim port had gpt-4o at
mini pricing — now corrected.
"""

from __future__ import annotations

from nova_ai.core.pricing import PRICING as PRICES  # noqa: F401 — re-export
from nova_ai.core.pricing import estimate_cost as _canonical_cost

# Models whose API rejects an explicit `temperature` param — callers should
# omit it for any model whose name starts with one of these prefixes.
NO_TEMP_PREFIXES: tuple[str, ...] = (
    "claude-opus-4-7",
    "claude-sonnet-4-7",
    "claude-haiku-4-7",
)


def cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """USD cost for one call. Unknown models price at 0 (e.g. local vLLM)."""
    return _canonical_cost(model, prompt_tokens, completion_tokens)


def supports_temperature(model: str) -> bool:
    return not model.startswith(NO_TEMP_PREFIXES)


def is_gpt5_family(model: str) -> bool:
    """GPT-5 series requires ``max_completion_tokens`` and forced temp=1."""
    return model.startswith("gpt-5")


def is_reasoning_model(model: str) -> bool:
    """Models that consume the output-token budget on hidden chain-of-thought
    before emitting visible answer text. At max_tokens=4096 these silently
    truncate with empty answers on GAIA (26/100 GPT-5, 18/100 Gemini Pro)."""
    m = (model or "").lower()
    return is_gpt5_family(model) or "gemini-2.5-pro" in m or "gemini-3.1-pro" in m


def default_max_output_tokens(model: str) -> int:
    """Sane default for ``max_tokens`` per cloud call. Reasoning models get
    a larger budget so their hidden thinking doesn't crowd out the answer."""
    return 16384 if is_reasoning_model(model) else 4096
