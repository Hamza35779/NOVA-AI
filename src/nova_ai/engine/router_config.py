from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(slots=True)
class RouterConfig:
    enabled: bool = False
    learning_enabled: bool = True
    feedback_window: int = 500  # max feedback records to consider
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
    # Serve models proven better per query class by the Model Proving Ground
    # (~/.nova_ai/learning/proving/policy_map.json). Off by default: proven
    # winners only take effect when the user opts in.
    proving_adoption: bool = False
