"""Tests for the SmartRouter proving-ground adoption hook.

The proving_adoption flag is off by default: these tests pin both the
disabled behavior (tier flow unchanged) and the enabled behavior (proven
model wins when servable).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from nova_ai.core.types import Message, RoutingContext
from nova_ai.engine.router import SmartRouter
from nova_ai.engine.router_config import RouterConfig
from nova_ai.learning.routing.learned_router import LearnedRouterPolicy


class FakeMulti:
    """MultiEngine stand-in: serves everything by default."""

    def __init__(self) -> None:
        self.served: list[str] = []

    def can_serve(self, model: str) -> bool:
        return model != "unservable-model"

    def list_models(self) -> list[str]:
        return ["tier-model", "proven-model"]

    def generate(self, messages, **kwargs):
        self.served.append(kwargs.get("model"))
        return {"content": "ok", "model": kwargs.get("model")}


@pytest.fixture()
def fake_optimizer():
    """Silence the self-optimizer dependency."""
    with mock.patch(
        "nova_ai.engine.router.get_optimizer"
    ) as m:
        opt = m.return_value
        opt.get_recommended_model_for_tier.return_value = ""
        yield opt


@pytest.fixture()
def proving_home(tmp_path: Path):
    """Redirect the proving root into tmp and return it."""
    with mock.patch(
        "nova_ai.core.paths.get_config_dir", return_value=tmp_path
    ):
        yield tmp_path


def _policy_map(tmp_path: Path, qclass: str = "code",
                model: str = "proven-model") -> None:
    root = tmp_path / "learning" / "proving"
    root.mkdir(parents=True, exist_ok=True)
    (root / "policy_map.json").write_text(json.dumps({
        qclass: {"model": model, "run_id": "prove_r1", "margin": 0.2,
                 "adopted_at": "t"},
    }))


CODE_QUERY = [Message(role="user", content="fix `def f(): pass` please")]


async def _collect(agen):
    """Drain an async generator into a list."""
    return [chunk async for chunk in agen]


class TestProvingAdoptionDisabled:
    def test_tier_flow_unchanged(
        self, fake_optimizer, proving_home: Path
    ) -> None:
        _policy_map(proving_home)
        engine = FakeMulti()
        router = SmartRouter(engine, RouterConfig(default_tier="large",
                                                  tiers={"large": "tier-model"}))
        assert router.generate(CODE_QUERY)["model"] == "tier-model"
        assert engine.served == ["tier-model"]

    def test_default_off_even_with_map_present(
        self, fake_optimizer, proving_home: Path
    ) -> None:
        _policy_map(proving_home)
        router = SmartRouter(
            FakeMulti(),
            RouterConfig(default_tier="large", tiers={"large": "tier-model"}),
        )
        assert router.config.proving_adoption is False


class TestProvingAdoptionEnabled:
    def _router(self, engine: FakeMulti) -> SmartRouter:
        return SmartRouter(
            engine,
            RouterConfig(default_tier="large", tiers={"large": "tier-model"},
                         proving_adoption=True),
        )

    def test_proven_model_served(self, fake_optimizer, proving_home: Path) -> None:
        _policy_map(proving_home)
        engine = FakeMulti()
        result = self._router(engine).generate(CODE_QUERY)
        assert result["model"] == "proven-model"
        assert engine.served == ["proven-model"]

    def test_unservable_model_falls_back(
        self, fake_optimizer, proving_home: Path
    ) -> None:
        _policy_map(proving_home, model="unservable-model")
        engine = FakeMulti()
        assert self._router(engine).generate(CODE_QUERY)["model"] == "tier-model"

    def test_no_map_entry_falls_back(
        self, fake_optimizer, proving_home: Path
    ) -> None:
        _policy_map(proving_home, qclass="math")  # query classifies as code
        engine = FakeMulti()
        assert self._router(engine).generate(CODE_QUERY)["model"] == "tier-model"

    def test_missing_map_falls_back(
        self, fake_optimizer, proving_home: Path
    ) -> None:
        engine = FakeMulti()
        assert self._router(engine).generate(CODE_QUERY)["model"] == "tier-model"

    def test_corrupt_map_falls_back(
        self, fake_optimizer, proving_home: Path
    ) -> None:
        root = proving_home / "learning" / "proving"
        root.mkdir(parents=True)
        (root / "policy_map.json").write_text("{oops")
        engine = FakeMulti()
        assert self._router(engine).generate(CODE_QUERY)["model"] == "tier-model"

    def test_stream_uses_proven_model_too(
        self, fake_optimizer, proving_home: Path
    ) -> None:
        """The stream paths apply the same proven-model override."""
        import asyncio

        _policy_map(proving_home)

        class StreamMulti(FakeMulti):
            async def stream(self, messages, **kwargs):
                yield kwargs.get("model") or "none"

        engine = StreamMulti()
        router = self._router(engine)
        chunks = list(asyncio.run(_collect(router.stream(CODE_QUERY))))
        assert chunks == ["proven-model"]

    def test_engine_without_can_serve_skips_check(
        self, fake_optimizer, proving_home: Path
    ) -> None:
        """Engines without can_serve are honored (lookup can't verify)."""
        _policy_map(proving_home)

        class Bare:
            """No can_serve at all — lookup must not crash on hasattr."""

            def list_models(self):
                return ["proven-model"]

            def generate(self, messages, **kwargs):
                return {"content": "ok", "model": kwargs.get("model")}

        engine = Bare()
        router = self._router(engine)
        assert router.generate(CODE_QUERY)["model"] == "proven-model"


class TestExplicitModelBypass:
    def test_explicit_model_skips_proven_lookup(
        self, fake_optimizer, proving_home: Path
    ) -> None:
        _policy_map(proving_home)
        engine = FakeMulti()
        router = SmartRouter(
            engine,
            RouterConfig(default_tier="large", tiers={"large": "tier-model"},
                         proving_adoption=True),
        )
        assert router.generate(CODE_QUERY, model="explicit-model")["model"] == (
            "explicit-model"
        )
        assert engine.served == ["explicit-model"]


class TestLearnedRouterPolicyPersistence:
    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "learned_policy.json"
        policy = LearnedRouterPolicy(available_models=["m-a"], policy_path=path)
        policy._policy_map["code"] = "m-a"
        policy._confidence["code"] = 3
        assert policy.save() == path

        reloaded = LearnedRouterPolicy(available_models=["m-a"], policy_path=path)
        assert reloaded.policy_map == {"code": "m-a"}
        # loaded entries pre-satisfy the confidence gate
        ctx = RoutingContext(query="fix `x` bug", query_length=10)
        assert reloaded.select_model(ctx) == "m-a"

    def test_save_without_path_is_noop(self, tmp_path: Path) -> None:
        policy = LearnedRouterPolicy()
        assert policy.save() is None
        assert policy.load() is False

    def test_load_missing_file_false(self, tmp_path: Path) -> None:
        policy = LearnedRouterPolicy(policy_path=tmp_path / "nope.json")
        assert policy.load() is False
        assert policy.policy_map == {}

    def test_load_corrupt_file_safe(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{oops")
        policy = LearnedRouterPolicy(policy_path=path)
        assert policy.load() is False
        assert policy.policy_map == {}

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "policy.json"
        policy = LearnedRouterPolicy(policy_path=path)
        policy._policy_map["code"] = "m-a"
        policy._confidence["code"] = 9
        assert policy.save() == path
        assert path.exists()

    def test_confidence_persisted_and_restored(self, tmp_path: Path) -> None:
        path = tmp_path / "policy.json"
        policy = LearnedRouterPolicy(policy_path=path)
        policy._policy_map["code"] = "m-a"
        policy._confidence["code"] = 12
        policy.save()
        reloaded = LearnedRouterPolicy(policy_path=path)
        assert reloaded._confidence["code"] == 12
