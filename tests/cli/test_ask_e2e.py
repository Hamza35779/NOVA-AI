"""End-to-end tests for ``nova ask``."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from nova_ai.cli import cli
from nova_ai.core.config import NovaConfig

# Import the actual module (not the Click command attribute)
_ask_mod = importlib.import_module("nova_ai.cli.ask")


def _mock_engine_response():
    """Return a mock engine that generates a fixed response."""
    return {
        "content": "The answer is 4.",
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
        "model": "test-model",
        "finish_reason": "stop",
    }


def _patch_ask(monkeypatch, tmp_path, *, engine_result=None, no_engine=False):
    """Set up common mocks for ask tests."""
    # Re-register SimpleAgent after the autouse `_clean_registries` conftest
    # fixture clears it. ``NovaConfig().agent.default_agent`` defaults to
    # ``"simple"``, so ``nova ask "..."`` (no --agent) routes through it.
    from nova_ai.agents.simple import SimpleAgent
    from nova_ai.core.registry import AgentRegistry

    if not AgentRegistry.contains("simple"):
        AgentRegistry.register_value("simple", SimpleAgent)

    cfg = NovaConfig()
    cfg.telemetry.db_path = str(tmp_path / "telemetry.db")

    monkeypatch.setattr(_ask_mod, "load_config", lambda: cfg)

    if no_engine:
        monkeypatch.setattr(_ask_mod, "get_engine", lambda *a, **kw: None)
    else:
        fake_engine = mock.MagicMock()
        fake_engine.engine_id = "mock"
        fake_engine.health.return_value = True
        fake_engine.generate.return_value = engine_result or _mock_engine_response()
        fake_engine.list_models.return_value = ["test-model"]
        monkeypatch.setattr(
            _ask_mod,
            "get_engine",
            lambda *a, **kw: ("mock", fake_engine),
        )
        monkeypatch.setattr(
            _ask_mod,
            "discover_engines",
            lambda c: [("mock", fake_engine)],
        )
        monkeypatch.setattr(
            _ask_mod,
            "discover_models",
            lambda e: {"mock": ["test-model"]},
        )


class TestAskCommand:
    def test_basic_response(self, monkeypatch, tmp_path: Path) -> None:
        _patch_ask(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["ask", "What is 2+2?"])
        assert result.exit_code == 0
        assert "The answer is 4" in result.output

    def test_no_engine_error(self, monkeypatch, tmp_path: Path) -> None:
        _patch_ask(monkeypatch, tmp_path, no_engine=True)
        result = CliRunner().invoke(cli, ["ask", "Hello"])
        assert result.exit_code != 0

    def test_tools_upgrade_simple_to_native_react(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        """--tools on a tool-blind default agent must not silently drop them."""
        from nova_ai.agents.native_react import NativeReActAgent
        from nova_ai.agents.simple import SimpleAgent
        from nova_ai.core.registry import AgentRegistry

        if not AgentRegistry.contains("simple"):
            AgentRegistry.register_value("simple", SimpleAgent)
        if not AgentRegistry.contains("native_react"):
            AgentRegistry.register_value("native_react", NativeReActAgent)
        _patch_ask(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["ask", "--tools", "think", "Hello"])
        assert result.exit_code == 0, result.output
        assert "switched to 'native_react'" in result.output

    def test_no_tools_keeps_default_agent(self, monkeypatch, tmp_path: Path) -> None:
        _patch_ask(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["ask", "Hello"])
        assert result.exit_code == 0
        assert "switched to" not in result.output

    def test_model_override(self, monkeypatch, tmp_path: Path) -> None:
        _patch_ask(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["ask", "-m", "custom-model", "Hello"])
        assert result.exit_code == 0

    def test_json_output(self, monkeypatch, tmp_path: Path) -> None:
        _patch_ask(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["ask", "--json", "Hello"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "content" in data

    def test_telemetry_recorded(self, monkeypatch, tmp_path: Path) -> None:
        _patch_ask(monkeypatch, tmp_path)
        CliRunner().invoke(cli, ["ask", "Hello"])
        db_path = tmp_path / "telemetry.db"
        assert db_path.exists()


class TestAskMissingModelHint:
    """Direct-mode 404s must print the fix, not escape as a traceback.

    Fresh install with a healthy engine but zero models: the startup
    fallback has nothing to switch to, and ``nova ask`` only used to catch
    ``EngineConnectionError`` — the Ollama missing-model ``RuntimeError``
    surfaced as an unhandled traceback.
    """

    def test_missing_model_404_prints_pull_hint(self, monkeypatch, tmp_path) -> None:
        cfg = NovaConfig()
        cfg.agent.default_agent = ""  # direct-to-engine mode
        cfg.intelligence.default_model = "qwen3.5:4b"
        cfg.telemetry.db_path = str(tmp_path / "telemetry.db")
        monkeypatch.setattr(_ask_mod, "load_config", lambda: cfg)

        fake_engine = mock.MagicMock()
        fake_engine.engine_id = "ollama"
        fake_engine.generate.side_effect = RuntimeError(
            "Ollama returned 404: model 'qwen3.5:4b' not found"
        )
        monkeypatch.setattr(
            _ask_mod, "get_engine", lambda *a, **kw: ("ollama", fake_engine)
        )
        monkeypatch.setattr(
            _ask_mod, "discover_engines", lambda c: [("ollama", fake_engine)]
        )
        monkeypatch.setattr(
            _ask_mod, "discover_models", lambda e: {"ollama": []}
        )

        result = CliRunner().invoke(cli, ["ask", "Hello"])

        assert result.exit_code == 1
        assert "Error: Ollama returned 404" in result.output
        assert "nova model pull qwen3.5:4b" in result.output
        assert "Traceback" not in result.output

    def test_unrelated_error_still_raises(self, monkeypatch, tmp_path) -> None:
        """Non-missing-model failures keep their original traceback."""
        cfg = NovaConfig()
        cfg.agent.default_agent = ""
        cfg.telemetry.db_path = str(tmp_path / "telemetry.db")
        monkeypatch.setattr(_ask_mod, "load_config", lambda: cfg)

        fake_engine = mock.MagicMock()
        fake_engine.engine_id = "ollama"
        fake_engine.generate.side_effect = RuntimeError("disk on fire")
        monkeypatch.setattr(
            _ask_mod, "get_engine", lambda *a, **kw: ("ollama", fake_engine)
        )
        monkeypatch.setattr(
            _ask_mod, "discover_engines", lambda c: [("ollama", fake_engine)]
        )
        monkeypatch.setattr(
            _ask_mod, "discover_models", lambda e: {"ollama": []}
        )

        result = CliRunner().invoke(cli, ["ask", "Hello"])

        assert result.exit_code != 0
        assert "nova model pull" not in result.output

    def test_agent_mode_missing_model_404_prints_pull_hint(
        self, monkeypatch, tmp_path
    ) -> None:
        """The default 'simple' agent surfaces the hint too (fresh install).

        ``nova init`` writes ``agent.default_agent = 'simple'``, so a new
        user's first ``nova ask`` goes through agent mode, not direct mode.
        """
        from nova_ai.agents.simple import SimpleAgent
        from nova_ai.core.registry import AgentRegistry

        if not AgentRegistry.contains("simple"):
            AgentRegistry.register_value("simple", SimpleAgent)

        cfg = NovaConfig()  # default_agent="simple" -> agent mode
        cfg.intelligence.default_model = "qwen3.5:4b"
        cfg.telemetry.db_path = str(tmp_path / "telemetry.db")
        monkeypatch.setattr(_ask_mod, "load_config", lambda: cfg)

        fake_engine = mock.MagicMock()
        fake_engine.engine_id = "ollama"
        fake_engine.generate.side_effect = RuntimeError(
            "Ollama returned 404: model 'qwen3.5:4b' not found"
        )
        monkeypatch.setattr(
            _ask_mod, "get_engine", lambda *a, **kw: ("ollama", fake_engine)
        )
        monkeypatch.setattr(
            _ask_mod, "discover_engines", lambda c: [("ollama", fake_engine)]
        )
        monkeypatch.setattr(
            _ask_mod, "discover_models", lambda e: {"ollama": []}
        )

        result = CliRunner().invoke(cli, ["ask", "Hello"])

        assert result.exit_code == 1
        assert "nova model pull qwen3.5:4b" in result.output
        assert "Traceback" not in result.output
