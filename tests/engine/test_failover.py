"""Tests for cloud model failover in MultiEngine (P1 reliability fix).

When a cloud generate call fails (transient outage, rate limit, bad key),
MultiEngine now walks the rest of the cloud preference list before failing —
instead of the error propagating immediately. Local models are never silently
swapped for cloud ones (explicit privacy/cost boundary).
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
        fail_on: set[str] | None = None,
    ) -> None:
        self._models = models
        self.is_cloud = is_cloud
        self.fail_on = fail_on or set()
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
        if model in self.fail_on:
            raise RuntimeError(f"engine down for {model}")
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


class TestCloudFailover:
    def test_no_failover_when_first_model_succeeds(self) -> None:
        local = _FakeEngine(["qwen3.5:9b"])
        cloud = _FakeEngine(["claude-sonnet-5", "gpt-5-mini"], is_cloud=True)
        multi = MultiEngine([("local", local), ("cloud", cloud)])

        result = multi.generate(_user("hi"), model="claude-sonnet-5")

        assert cloud.calls == ["claude-sonnet-5"]
        assert result["content"] == "from claude-sonnet-5"

    def test_fails_when_model_owned_by_no_engine(self) -> None:
        local = _FakeEngine(["qwen3.5:9b"])
        cloud = _FakeEngine(["claude-sonnet-5"], is_cloud=True)
        multi = MultiEngine([("local", local), ("cloud", cloud)])

        with pytest.raises(ValueError, match="not found in any engine"):
            multi.generate(_user("hi"), model="does-not-exist")

    def test_error_propagates_when_no_alternative_cloud_model(self) -> None:
        local = _FakeEngine(["qwen3.5:9b"])
        cloud = _FakeEngine(["claude-sonnet-5"], is_cloud=True, fail_on={"claude-sonnet-5"})
        multi = MultiEngine([("local", local), ("cloud", cloud)])

        with pytest.raises(RuntimeError, match="engine down"):
            multi.generate(_user("hi"), model="claude-sonnet-5")
        # Never routed to local as a silent fallback.
        assert local.calls == []

    def test_fails_when_model_unknown_and_cloud_down(self) -> None:
        local = _FakeEngine(["qwen3.5:9b"])
        cloud = _FakeEngine(["claude-sonnet-5"], is_cloud=True, fail_on={"gpt-unknown-9"})
        multi = MultiEngine([("local", local), ("cloud", cloud)])

        with pytest.raises(RuntimeError, match="engine down"):
            multi.generate(_user("hi"), model="gpt-unknown-9")

    def test_fails_when_explicit_local_model_fails(self) -> None:
        local = _FakeEngine(["qwen3.5:9b"], fail_on={"qwen3.5:9b"})
        cloud = _FakeEngine(["claude-sonnet-5"], is_cloud=True)
        multi = MultiEngine([("local", local), ("cloud", cloud)])

        with pytest.raises(RuntimeError, match="engine down"):
            multi.generate(_user("hi"), model="qwen3.5:9b")
        assert cloud.calls == []

    def test_auto_failover_to_next_cloud_model(self) -> None:
        local = _FakeEngine(["qwen3.5:9b"])
        cloud = _FakeEngine(
            ["claude-sonnet-5", "gpt-5", "gpt-5-mini"],
            is_cloud=True,
            fail_on={"claude-sonnet-5", "gpt-5"},
        )
        multi = MultiEngine([("local", local), ("cloud", cloud)])

        result = multi.generate(
            _user(COMPLEX_QUERY),
            model=AUTO_MODEL,
        )

        # Walked the preference list past the two dead models.
        assert cloud.calls == ["claude-sonnet-5", "gpt-5", "gpt-5-mini"]
        assert result["content"] == "from gpt-5-mini"
        assert result["_routing"]["failed_over"] is True
        assert result["_routing"]["model"] == "gpt-5-mini"

    def test_auto_no_failover_when_first_succeeds(self) -> None:
        local = _FakeEngine(["qwen3.5:9b"])
        cloud = _FakeEngine(["claude-sonnet-5", "gpt-5-mini"], is_cloud=True)
        multi = MultiEngine([("local", local), ("cloud", cloud)])

        result = multi.generate(
            _user(COMPLEX_QUERY),
            model=AUTO_MODEL,
        )

        assert cloud.calls == ["claude-sonnet-5"]
        assert result["_routing"]["failed_over"] is False
