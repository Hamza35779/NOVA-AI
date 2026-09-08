"""Tests for MorningDigestAgent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nova_ai.agents._stubs import AgentResult
from nova_ai.core.registry import AgentRegistry
from nova_ai.core.types import ToolResult


def test_morning_digest_registered():
    from nova_ai.agents.morning_digest import MorningDigestAgent

    AgentRegistry.register_value("morning_digest", MorningDigestAgent)
    assert AgentRegistry.contains("morning_digest")


def test_morning_digest_run(tmp_path):
    from nova_ai.agents.morning_digest import MorningDigestAgent

    mock_engine = MagicMock()
    mock_engine.generate.return_value = {
        "content": "Good morning sir. You have 3 emails and 2 meetings today.",
        "finish_reason": "stop",
        "usage": {},
    }

    # Mock collect result
    mock_collect_result = ToolResult(
        tool_name="digest_collect",
        content='=== MESSAGES ===\n[gmail] From: alice@co.com — "Budget" (1h ago)\n',
        success=True,
        metadata={"total_items": 2},
    )

    # Mock TTS result
    mock_tts_result = ToolResult(
        tool_name="text_to_speech",
        content=str(tmp_path / "digest.mp3"),
        success=True,
        metadata={"audio_path": str(tmp_path / "digest.mp3")},
    )

    agent = MorningDigestAgent(
        mock_engine,
        "test-model",
        tools=[],
        persona="neutral",
        digest_store_path=str(tmp_path / "digest.db"),
    )

    with patch.object(
        agent._executor,
        "execute",
        side_effect=[mock_collect_result, mock_tts_result],
    ):
        result = agent.run("Generate morning digest")

    assert isinstance(result, AgentResult)
    assert "Good morning" in result.content
    assert result.turns == 1
    assert len(result.tool_results) == 2


def test_load_persona():
    from nova_ai.agents.morning_digest import _load_persona

    # Nonexistent persona returns empty string
    result = _load_persona("nonexistent_persona_xyz")
    assert result == ""


def test_morning_digest_sends_desktop_notification(tmp_path):
    """A stored digest fires a desktop notification with a snippet."""
    from nova_ai.agents.morning_digest import MorningDigestAgent

    mock_engine = MagicMock()
    mock_engine.generate.return_value = {
        "content": "Good morning sir. You have 3 emails and 2 meetings today.",
        "finish_reason": "stop",
        "usage": {},
    }
    mock_collect_result = ToolResult(
        tool_name="digest_collect",
        content="=== MESSAGES ===\n[gmail] From: alice@co.com — \"Budget\" (1h ago)\n",
        success=True,
        metadata={"total_items": 2},
    )
    mock_tts_result = ToolResult(
        tool_name="text_to_speech",
        content=str(tmp_path / "digest.mp3"),
        success=True,
        metadata={"audio_path": str(tmp_path / "digest.mp3")},
    )

    agent = MorningDigestAgent(
        mock_engine,
        "test-model",
        tools=[],
        persona="neutral",
        digest_store_path=str(tmp_path / "digest.db"),
    )

    notifier = MagicMock()
    with patch.object(agent._executor, "execute", side_effect=[mock_collect_result, mock_tts_result]), \
         patch("nova_ai.notifications.notifier.get_notifier", return_value=notifier):
        agent.run("Generate morning digest")

    notifier.send.assert_called_once()
    kwargs = notifier.send.call_args.kwargs
    assert kwargs["title"] == "Morning digest ready"
    assert "Good morning" in kwargs["message"]


def test_morning_digest_notification_failure_is_soft(tmp_path):
    """A broken notifier must not fail digest delivery."""
    from nova_ai.agents.morning_digest import MorningDigestAgent

    mock_engine = MagicMock()
    mock_engine.generate.return_value = {
        "content": "Good morning sir.",
        "finish_reason": "stop",
        "usage": {},
    }
    mock_collect_result = ToolResult(
        tool_name="digest_collect", content="=== MESSAGES ===\nx", success=True
    )
    mock_tts_result = ToolResult(
        tool_name="text_to_speech",
        content=str(tmp_path / "digest.mp3"),
        success=True,
        metadata={"audio_path": str(tmp_path / "digest.mp3")},
    )

    agent = MorningDigestAgent(
        mock_engine,
        "test-model",
        tools=[],
        persona="neutral",
        digest_store_path=str(tmp_path / "digest.db"),
    )

    with patch.object(agent._executor, "execute", side_effect=[mock_collect_result, mock_tts_result]), \
         patch("nova_ai.notifications.notifier.get_notifier", side_effect=RuntimeError("boom")):
        result = agent.run("Generate morning digest")

    assert isinstance(result, AgentResult)
    assert "Good morning" in result.content
