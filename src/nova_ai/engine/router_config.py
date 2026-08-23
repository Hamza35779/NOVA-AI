from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(slots=True)
class RouterConfig:
    enabled: bool = False
    tiers: Dict[str, str] = field(
        default_factory=lambda: {
            "small": "qwen2.5:0.5b",
            "medium": "qwen2.5:7b",
            "large": "qwen2.5:32b",
        }
    )
    short_query_max_chars: int = 100
    medium_query_max_chars: int = 500
    tool_use_tier: str = "medium"
    research_tier: str = "large"
    code_tier: str = "large"
    default_tier: str = "medium"
