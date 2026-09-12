"""Pricing single-source regression (B3)."""

from nova_ai.agents.hybrid import _prices as hybrid_prices
from nova_ai.core import pricing as core_pricing
from nova_ai.engine import cloud as cloud_engine


def test_gpt4o_is_full_price_not_mini():
    # B3: hybrid table had gpt-4o at mini pricing (0.15/0.60).
    assert core_pricing.PRICING["gpt-4o"] == (2.50, 10.00)
    assert core_pricing.PRICING["gpt-4o-mini"] == (0.15, 0.60)


def test_tables_agree():
    assert cloud_engine.PRICING is core_pricing.PRICING
    assert hybrid_prices.PRICES is core_pricing.PRICING
    assert cloud_engine.estimate_cost("gpt-4o", 1_000_000, 0) == 2.50
    assert hybrid_prices.cost("gpt-4o", 1_000_000, 0) == 2.50
