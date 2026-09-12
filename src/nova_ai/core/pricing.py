"""Canonical provider pricing — single source of truth (B3 fix).

Merges the two conflicting tables:
- ``engine/cloud.py::PRICING`` (correct: gpt-4o = 2.50/10.00)
- ``agents/hybrid/_prices.py::PRICES`` (had gpt-4o = 0.15/0.60, which is
  actually gpt-4o-*mini* pricing)

Rule: engine numbers win for overlapping keys; hybrid-only OpenRouter slugs
are preserved. All cost code should import from here.
"""

from __future__ import annotations

# USD per million tokens: (input, output). Local models = 0 (absent = 0).
PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-5.6-sol": (15.00, 60.00),
    "gpt-5.6": (15.00, 60.00),
    "gpt-5.4": (15.00, 60.00),
    "gpt-5.5": (5.00, 30.0),
    "gpt-5": (10.00, 30.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-mini-2025-08-07": (0.25, 2.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "o3-mini": (1.10, 4.40),
    # Anthropic
    "claude-opus-5": (15.00, 75.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-4-7": (5.00, 25.0),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-opus-4-20250514": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    # Google (low-context standard rate; Pro tiered above 200k)
    "gemini-3.7-pro": (2.50, 15.00),
    "gemini-3.7-flash": (0.50, 3.00),
    "gemini-3.1-pro-preview": (2.00, 12.0),
    "gemini-3.1-pro-preview-customtools": (2.00, 12.0),
    "gemini-3-pro": (2.00, 12.00),
    "gemini-3-flash": (0.50, 3.00),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    # xAI
    "grok-4.5": (5.00, 25.00),
    "grok-4": (4.00, 20.00),
    "grok-3": (3.00, 15.00),
    "grok-2": (2.00, 10.00),
    # MiniMax / DeepSeek
    "MiniMax-M2.7": (0.30, 1.20),
    "MiniMax-M2.7-highspeed": (0.60, 2.40),
    "MiniMax-M2.5": (0.30, 1.20),
    "MiniMax-M2.5-highspeed": (0.60, 2.40),
    "deepseek-v4-flash": (0.27, 1.10),
    "deepseek-v4-pro": (0.55, 2.19),
    # OpenRouter slugs (2026-05 snapshot)
    "qwen/qwen-2.5-coder-32b-instruct": (0.08, 0.18),
    "qwen/qwen3-32b": (0.10, 0.30),
    "meta-llama/llama-3.3-70b-instruct": (0.13, 0.39),
}

# Back-compat alias (hybrid code used PRICES)
PRICES = PRICING


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """USD cost; exact match then prefix match; unknown → 0.0 (local)."""
    prices = PRICING.get(model)
    if prices is None:
        for key, val in PRICING.items():
            if model.startswith(key):
                prices = val
                break
    if prices is None:
        return 0.0
    return (prompt_tokens / 1_000_000) * prices[0] + (
        completion_tokens / 1_000_000
    ) * prices[1]


__all__ = ["PRICING", "PRICES", "estimate_cost"]
