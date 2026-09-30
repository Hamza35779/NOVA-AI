"""Tests for the Colibrì engine (OpenAI-compatible ``coli serve`` gateway).

The engine itself is a generated ``_OpenAICompatibleEngine`` subclass, so
these tests focus on the Colibrì-specific wiring: registry entry, default
host/prefix, env-var overrides, config plumbing, and discovery.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from nova_ai.core.config import HardwareInfo, NovaConfig
from nova_ai.core.config.loader import _apply_toml_section
from nova_ai.core.registry import EngineRegistry
from nova_ai.core.types import Message, Role
from nova_ai.engine._discovery import _HOST_MAP, _make_engine
from nova_ai.engine.openai_compat_engines import ColibriEngine


@pytest.fixture(autouse=True)
def _register_colibri():
    """Re-register after conftest's registry clear."""
    EngineRegistry.register_value("colibri", ColibriEngine)
    yield


class TestRegistry:
    def test_registered_in_engine_registry(self):
        assert EngineRegistry.contains("colibri")
        assert EngineRegistry.get("colibri") is ColibriEngine

    def test_default_host_and_prefix(self):
        assert ColibriEngine._default_host == "http://localhost:8000"
        assert ColibriEngine._api_prefix == "/v1"

    def test_default_construction(self):
        engine = ColibriEngine()
        assert engine._host == "http://localhost:8000"

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("COLIBRI_HOST", "http://10.0.0.9:9000")
        monkeypatch.setenv("COLIBRI_API_KEY", "secret")
        engine = ColibriEngine()
        assert engine._host == "http://10.0.0.9:9000"
        assert engine._api_key == "secret"


class TestConfigPlumbing:
    def test_config_section_defaults(self):
        cfg = NovaConfig()
        assert cfg.engine.colibri.host == "http://localhost:8000"

    def test_toml_section_applies(self):
        cfg = NovaConfig()
        _apply_toml_section(cfg.engine, {"colibri": {"host": "http://box:8123"}})
        assert cfg.engine.colibri.host == "http://box:8123"

    def test_backcompat_host_property(self):
        cfg = NovaConfig()
        cfg.engine.colibri.host = "http://box:8123"
        assert cfg.engine.colibri_host == "http://box:8123"

    def test_discovery_uses_config_host(self):
        cfg = NovaConfig()
        cfg.engine.colibri.host = "http://colibri-box:8123"
        engine = _make_engine("colibri", cfg)
        assert isinstance(engine, ColibriEngine)
        assert engine._host == "http://colibri-box:8123"

    def test_host_map_entry(self):
        assert _HOST_MAP["colibri"] == "colibri_host"


class TestGenerate:
    def test_generate_through_colibri_endpoint(self):
        engine = ColibriEngine(host="http://colitest:8000")
        with respx.mock:
            respx.post("http://colitest:8000/v1/chat/completions").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "choices": [
                            {"message": {"content": "Ciao!"}, "finish_reason": "stop"}
                        ],
                        "usage": {
                            "prompt_tokens": 5,
                            "completion_tokens": 3,
                            "total_tokens": 8,
                        },
                        "model": "glm52",
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="ciao")], model="glm52"
            )
        assert result["content"] == "Ciao!"
        assert result["usage"]["total_tokens"] == 8


class TestModelRecommendation:
    def test_colibri_recommends_empty(self):
        from nova_ai.core.config.models import recommend_model

        hw = HardwareInfo(platform="windows", cpu_brand="Test", ram_gb=64.0)
        assert recommend_model(hw, "colibri") == ""
