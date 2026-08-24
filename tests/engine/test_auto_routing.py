"""Tests for complexity-driven auto routing in MultiEngine (roadmap WS3).

``model="auto"`` scores the last user message and escalates to cloud at or
above the threshold; everything else stays on the first local engine.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

import pytest

from nova_ai.core.types import Message, Role
from nova_ai.engine._base import InferenceEngine
from nova_ai.engine.multi import AUTO_MODEL, MultiEngine


class _FakeEngine(InferenceEngine):
    engine_id = "fake"

    def __init__(
        self,
        models: List[str],
        *,
        is_cloud: bool = False,
    ) -> None:
        self._models = models
        self.is_cloud = is_cloud
        self.calls: List[str] = []

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        self.calls.append(model)
        return {"content": f"from {model}"}

    async def stream(self, messages, *, model, **kwargs):  # type: ignore[override]
        self.calls.append(model)
        yield f"from {model}"

    def list_models(self) -> List[str]:
        return list(self._models)

    def health(self) -> bool:
        return True


COMPLEX_QUERY = (
    "Analyze the following code step by step, then explain why the "
    "algorithm is incorrect, propose a fix, and write a detailed proof "
    "of correctness including trade-offs:\n"
    "1. First trace the loop invariants.\n"
    "2. Next derive the recurrence.\n"
    "```python\ndef f(n):\n    return n / 0\n```\n"
)


def _user(text: str) -> list[Message]:
    return [Message(role=Role.USER, content=text)]


class TestAutoRouting:
    def test_simple_query_stays_local(self) -> None:
        local = _FakeEngine(["qwen3.5:9b"])
        cloud = _FakeEngine(
            ["claude-sonnet-5", "gpt-5-mini"], is_cloud=True
        )
        multi = MultiEngine([("local", local), ("cloud", cloud)])

        result = multi.generate(_user("hi"), model=AUTO_MODEL)

        assert local.calls == ["qwen3.5:9b"]
        assert cloud.calls == []
        assert result["_routing"]["route"] == "local"

    def test_complex_query_escalates_to_cloud(self) -> None:
        local = _FakeEngine(["qwen3.5:9b"])
        cloud = _FakeEngine(["claude-sonnet-5"], is_cloud=True)
        multi = MultiEngine([("local", local), ("cloud", cloud)])

        result = multi.generate(_user(COMPLEX_QUERY), model=AUTO_MODEL)

        assert cloud.calls == ["claude-sonnet-5"]
        assert result["_routing"]["route"] == "cloud"
        assert result["_routing"]["complexity_tier"] in ("complex", "very_complex")

    def test_complex_query_without_cloud_stays_local(self) -> None:
        local = _FakeEngine(["qwen3.5:9b"])
        multi = MultiEngine([("local", local)])

        result = multi.generate(_user(COMPLEX_QUERY), model=AUTO_MODEL)

        assert local.calls == ["qwen3.5:9b"]
        assert result["_routing"]["reason"] == "cloud_unavailable"

    def test_preference_order_respected_and_missing_skipped(self) -> None:
        local = _FakeEngine(["qwen3.5:9b"])
        # Only gpt-5-mini configured; preferred claude/gpt-5 absent.
        cloud = _FakeEngine(["gpt-5-mini"], is_cloud=True)
        multi = MultiEngine([("local", local), ("cloud", cloud)])

        multi.generate(_user(COMPLEX_QUERY), model=AUTO_MODEL)

        assert cloud.calls == ["gpt-5-mini"]

    @pytest.mark.asyncio
    async def test_stream_resolves_auto_alias(self) -> None:
        local = _FakeEngine(["qwen3.5:9b"])
        cloud = _FakeEngine(["claude-sonnet-5"], is_cloud=True)
        multi = MultiEngine([("local", local), ("cloud", cloud)])

        chunks = [c async for c in multi.stream(_user("hello"), model=AUTO_MODEL)]

        assert chunks == ["from qwen3.5:9b"]
        assert local.calls == ["qwen3.5:9b"]

    def test_real_models_bypass_resolution(self) -> None:
        local = _FakeEngine(["qwen3.5:9b"])
        cloud = _FakeEngine(["claude-sonnet-5"], is_cloud=True)
        multi = MultiEngine([("local", local), ("cloud", cloud)])

        result = multi.generate(_user(COMPLEX_QUERY), model="claude-sonnet-5")

        # Explicit model: no auto resolution, no _routing key.
        assert "_routing" not in result
        assert cloud.calls == ["claude-sonnet-5"]

    def test_auto_listed_when_multiple_engines(self) -> None:
        local = _FakeEngine(["qwen3.5:9b"])
        cloud = _FakeEngine(["claude-sonnet-5"], is_cloud=True)
        multi = MultiEngine([("local", local), ("cloud", cloud)])
        assert AUTO_MODEL in multi.list_models()

    def test_auto_not_listed_for_single_engine(self) -> None:
        local = _FakeEngine(["qwen3.5:9b"])
        multi = MultiEngine([("local", local)])
        assert AUTO_MODEL not in multi.list_models()
