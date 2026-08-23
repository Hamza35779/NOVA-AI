from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nova_ai.core.types import Message
from nova_ai.engine.router import SmartRouter
from nova_ai.engine.router_config import RouterConfig


@pytest.fixture
def router() -> SmartRouter:
    mock_engine = MagicMock()
    mock_engine.generate.return_value = {"content": "mock response"}
    return SmartRouter(engine=mock_engine, config=RouterConfig())


def test_short_greeting_routes_to_small(router: SmartRouter) -> None:
    messages = [Message(role="user", content="hello!")]
    tier = router.classify_complexity(messages)
    assert tier == "small"


def test_complex_analysis_routes_to_large(router: SmartRouter) -> None:
    messages = [
        Message(role="user", content="Please analyze the following data and compare...")
    ]
    tier = router.classify_complexity(messages)
    assert tier == "large"


def test_code_block_routes_to_code_tier(router: SmartRouter) -> None:
    messages = [Message(role="user", content="```python\ndef solve(): pass\n```")]
    tier = router.classify_complexity(messages)
    assert tier == "large"


def test_medium_query_routes_to_medium(router: SmartRouter) -> None:
    content = "a" * 200  # Over 100, less than 500
    messages = [Message(role="user", content=content)]
    tier = router.classify_complexity(messages)
    assert tier == "medium"


def test_explicit_model_bypasses_router(router: SmartRouter) -> None:
    messages = [Message(role="user", content="hi")]
    router.generate(messages, model="custom-model")
    router.engine.generate.assert_called_once_with(messages, model="custom-model")
    stats = router.get_routing_stats()
    assert stats["bypassed"] == 1
    assert stats["small"] == 0
    assert stats["total_requests"] == 1


def test_tool_use_bumps_to_medium(router: SmartRouter) -> None:
    messages = [Message(role="user", content="hi")]
    tier = router.classify_complexity(messages, tools=[{"type": "function"}])
    assert tier == "medium"
