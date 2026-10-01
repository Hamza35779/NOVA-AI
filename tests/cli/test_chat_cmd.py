"""Tests for ``nova chat`` interactive REPL command."""

from __future__ import annotations

from unittest import mock
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from nova_ai.agents._stubs import (
    AgentContext,
    AgentResult,
    BaseAgent,
    ToolUsingAgent,
)
from nova_ai.cli.chat_cmd import _read_input, chat
from nova_ai.core.config import NovaConfig
from nova_ai.core.registry import AgentRegistry, ToolRegistry
from nova_ai.core.types import ToolCall, ToolResult
from nova_ai.tools._stubs import BaseTool, ToolSpec


class _SimpleChatAgent(BaseAgent):
    agent_id = "simple_chat_agent"

    def run(self, input, context: AgentContext | None = None, **kwargs):
        return AgentResult(content="simple ok", turns=1)


class _DangerousChatTool(BaseTool):
    tool_id = "dangerous_chat"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="dangerous_chat",
            description="Confirmation-gated chat tool.",
            requires_confirmation=True,
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(
            tool_name="dangerous_chat",
            content="chat executed!",
            success=True,
        )


class _ToolChatAgent(ToolUsingAgent):
    agent_id = "tool_chat_agent"

    def run(self, input, context: AgentContext | None = None, **kwargs):
        result = self._executor.execute(
            ToolCall(id="chat", name="dangerous_chat", arguments="{}")
        )
        return AgentResult(content=result.content, tool_results=[result], turns=1)


class _RecoverAgent(BaseAgent):
    """Only answers once its model has been swapped to an installed one."""

    agent_id = "recover_agent"

    def run(self, input, context: AgentContext | None = None, **kwargs):
        if self._model != "qwen2.5:0.5b":
            raise RuntimeError("Ollama returned 404: model 'qwen3.5:4b' not found")
        return AgentResult(content="agent recovered", turns=1)


class TestChatCommand:
    """Test the Click command definition and help output."""

    def test_command_exists(self) -> None:
        result = CliRunner().invoke(chat, ["--help"])
        assert result.exit_code == 0
        assert "interactive" in result.output.lower() or "chat" in result.output.lower()

    def test_options(self) -> None:
        result = CliRunner().invoke(chat, ["--help"])
        assert result.exit_code == 0
        assert "--engine" in result.output
        assert "--model" in result.output
        assert "--agent" in result.output
        assert "--tools" in result.output
        assert "--system" in result.output

    def test_slash_commands_listed(self) -> None:
        result = CliRunner().invoke(chat, ["--help"])
        assert result.exit_code == 0
        assert "/quit" in result.output


class TestReadInput:
    """Test the _read_input helper function."""

    def test_read_input_eof(self) -> None:
        with mock.patch("builtins.input", side_effect=EOFError):
            assert _read_input() is None

    def test_read_input_keyboard_interrupt(self) -> None:
        with mock.patch("builtins.input", side_effect=KeyboardInterrupt):
            assert _read_input() is None

    def test_read_input_normal(self) -> None:
        with mock.patch("builtins.input", return_value="hello"):
            assert _read_input() == "hello"


class TestChatAgents:
    def test_simple_agent_does_not_receive_tool_only_kwargs(self) -> None:
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = {"content": "engine fallback"}
        config = NovaConfig()
        config.intelligence.default_model = "test-model"

        AgentRegistry.register_value("simple_chat_agent", _SimpleChatAgent)

        with (
            patch("nova_ai.cli.chat_cmd.load_config", return_value=config),
            patch("nova_ai.engine.get_engine", return_value=("mock", engine)),
            patch("nova_ai.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(
                chat,
                ["--agent", "simple_chat_agent", "--model", "test-model"],
                input="hello\n/quit\n",
            )

        assert result.exit_code == 0
        assert "simple ok" in result.output
        assert "failed" not in result.output.lower()

    def test_tool_agent_uses_legacy_agent_tools_and_prompts_confirmation(self) -> None:
        engine = MagicMock()
        engine.engine_id = "mock"
        config = NovaConfig()
        config.intelligence.default_model = "test-model"
        config.agent.tools = "dangerous_chat"
        config.agent.max_turns = 3

        AgentRegistry.register_value("tool_chat_agent", _ToolChatAgent)
        ToolRegistry.register_value("dangerous_chat", _DangerousChatTool)

        with (
            patch("nova_ai.cli.chat_cmd.load_config", return_value=config),
            patch("nova_ai.engine.get_engine", return_value=("mock", engine)),
            patch("nova_ai.intelligence.register_builtin_models"),
        ):
            result = CliRunner().invoke(
                chat,
                ["--agent", "tool_chat_agent", "--model", "test-model"],
                input="run tool\ny\n/quit\n",
            )

        assert result.exit_code == 0
        assert "Confirm:" in result.output
        assert "chat executed!" in result.output


class TestChatModelFallback:
    """The REPL must not die on a configured-but-missing model (audit FP-A).

    ``nova ask`` and ``nova serve`` fall back to an installed model with a
    notice when the configured default isn't installed; ``nova chat`` used
    to trust the config blindly and hit a raw ``Ollama returned 404`` on
    the first message. These tests pin the mirrored fallback behavior.
    """

    @staticmethod
    def _make_config(default_model: str, fallback_model: str = "") -> NovaConfig:
        config = NovaConfig()
        config.intelligence.default_model = default_model
        config.intelligence.fallback_model = fallback_model
        config.agent.default_agent = ""  # direct-to-engine mode
        return config

    @classmethod
    def _invoke_chat(
        cls,
        config: NovaConfig,
        engine: MagicMock,
        discovered: dict | list,
        args: list[str] | None = None,
    ):
        """Run the REPL with discovery stubbed.

        ``discovered`` is either a single snapshot dict, or a list of
        snapshots consumed across successive discovery calls (startup,
        then mid-session recovery).
        """
        engine.engine_id = "ollama"
        engine.generate.return_value = {"content": "repl reply"}
        discovery_kwargs = (
            {"side_effect": list(discovered)}
            if isinstance(discovered, list)
            else {"return_value": discovered}
        )
        with (
            patch("nova_ai.cli.chat_cmd.load_config", return_value=config),
            patch("nova_ai.engine.get_engine", return_value=("ollama", engine)),
            patch("nova_ai.intelligence.register_builtin_models"),
            patch(
                "nova_ai.engine.discover_engines",
                return_value=[("ollama", engine)],
            ),
            patch("nova_ai.engine.discover_models", **discovery_kwargs),
        ):
            return CliRunner().invoke(chat, list(args or []), input="hello\n/quit\n")

    def test_missing_configured_model_falls_back_to_installed(self) -> None:
        """Config default not installed -> notice + first installed model."""
        engine = MagicMock()
        config = self._make_config("qwen3.5:4b")
        result = self._invoke_chat(
            config,
            engine,
            {"ollama": ["qwen2.5:0.5b", "qwen3:0.6b"]},
        )

        assert result.exit_code == 0
        assert "not reachable" in result.output
        assert "qwen2.5:0.5b" in result.output
        assert engine.generate.call_args.kwargs["model"] == "qwen2.5:0.5b"

    def test_fallback_model_from_config_preferred(self) -> None:
        """intelligence.fallback_model wins over first discovered model."""
        engine = MagicMock()
        config = self._make_config("qwen3.5:4b", fallback_model="qwen3:0.6b")
        result = self._invoke_chat(
            config,
            engine,
            {"ollama": ["qwen2.5:0.5b", "qwen3:0.6b"]},
        )

        assert result.exit_code == 0
        assert "not reachable" in result.output
        assert engine.generate.call_args.kwargs["model"] == "qwen3:0.6b"

    def test_explicit_model_flag_also_falls_back(self) -> None:
        """--model naming an uninstalled model falls back too (like ask)."""
        engine = MagicMock()
        config = self._make_config("")
        result = self._invoke_chat(
            config,
            engine,
            {"ollama": ["qwen2.5:0.5b"]},
            args=["--model", "ghost-model"],
        )

        assert result.exit_code == 0
        assert "not reachable" in result.output
        assert engine.generate.call_args.kwargs["model"] == "qwen2.5:0.5b"

    def test_reachable_configured_model_is_untouched(self) -> None:
        """No notice and no substitution when the model is installed."""
        engine = MagicMock()
        config = self._make_config("qwen3:0.6b")
        result = self._invoke_chat(
            config,
            engine,
            {"ollama": ["qwen2.5:0.5b", "qwen3:0.6b"]},
        )

        assert result.exit_code == 0
        assert "not reachable" not in result.output
        assert engine.generate.call_args.kwargs["model"] == "qwen3:0.6b"

    def test_empty_discovery_keeps_configured_model(self) -> None:
        """Discovery useless (no models listed) -> never a hard gate."""
        engine = MagicMock()
        config = self._make_config("qwen3.5:4b")
        result = self._invoke_chat(config, engine, {})

        assert result.exit_code == 0
        assert "not reachable" not in result.output
        assert engine.generate.call_args.kwargs["model"] == "qwen3.5:4b"

    def test_midsession_missing_model_recovers_and_retries(self) -> None:
        """404 on generate mid-session -> swap to an installed model, retry."""
        engine = MagicMock()
        config = self._make_config("qwen3.5:4b")
        engine.generate.side_effect = [
            RuntimeError("Ollama returned 404: model 'qwen3.5:4b' not found"),
            {"content": "recovered reply"},
        ]
        # Discovery empty at startup (engine still warming up), models
        # visible by the time the recovery re-check runs.
        result = self._invoke_chat(
            config,
            engine,
            [{}, {"ollama": ["qwen2.5:0.5b", "qwen3:0.6b"]}],
        )

        assert result.exit_code == 0
        assert "not reachable" in result.output
        assert "recovered reply" in result.output
        assert engine.generate.call_count == 2
        assert engine.generate.call_args.kwargs["model"] == "qwen2.5:0.5b"

    def test_midsession_recovery_swaps_agent_model(self) -> None:
        """Agent-mode turns recover too: notice + set_model + retry."""
        engine = MagicMock()
        config = self._make_config("qwen3.5:4b")
        AgentRegistry.register_value("recover_agent", _RecoverAgent)
        result = self._invoke_chat(
            config,
            engine,
            [{}, {"ollama": ["qwen2.5:0.5b"]}],
            args=["--agent", "recover_agent"],
        )

        assert result.exit_code == 0
        assert "not reachable" in result.output
        assert "agent recovered" in result.output
