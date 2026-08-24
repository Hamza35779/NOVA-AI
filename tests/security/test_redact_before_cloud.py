"""Tests for the redaction-before-cloud pipeline (roadmap WS3).

Covers the shared ``redact_messages`` helper and the mandatory scrub inside
``cloud_router.stream_cloud`` — the two layers that keep secrets/PII from
reaching cloud providers even when callers bypass GuardrailsEngine.
"""

from __future__ import annotations

from typing import Any

import pytest

from nova_ai.core.types import Message, Role
from nova_ai.security.guardrails import redact_messages


def _last_sent_texts(monkeypatch: pytest.MonkeyPatch):
    """Patch cloud_router's provider streamers to capture outbound messages.

    Returns a list that will receive the message-content lists handed to the
    (faked) OpenAI-compatible streamer.
    """
    captured: list[list[dict[str, Any]]] = []

    async def fake_stream_openai(
        model, messages, temperature, max_tokens, **kwargs
    ):
        captured.append(
            [{"role": m.role.value, "content": m.content} for m in messages]
        )
        yield "ok"

    import nova_ai.server.cloud_router as cr

    monkeypatch.setattr(cr, "_stream_openai", fake_stream_openai)
    return captured


class TestRedactMessages:
    def test_secrets_are_scrubbed_from_content(self) -> None:
        msgs = [Message(role=Role.USER, content="use key sk-live-abcdef0123456789")]
        out = redact_messages(msgs)
        assert "sk-live-abcdef0123456789" not in out[0].content
        # Original untouched
        assert msgs[0].content == "use key sk-live-abcdef0123456789"

    def test_clean_messages_pass_through_unchanged(self) -> None:
        msgs = [Message(role=Role.USER, content="what is 2+2?")]
        out = redact_messages(msgs)
        assert out[0] is msgs[0]

    def test_empty_content_preserved(self) -> None:
        msgs = [Message(role=Role.ASSISTANT, content="")]
        out = redact_messages(msgs)
        assert out[0] is msgs[0]

    def test_message_fields_preserved(self) -> None:
        # 36 chars after ghp_ = the scanner's minimum GitHub-token length.
        gh_token = "ghp_" + "a" * 36
        msgs = [
            Message(role=Role.USER, content=f"token: {gh_token}", name="tester")
        ]
        out = redact_messages(msgs)
        assert out[0].name == "tester"
        assert out[0].role == Role.USER
        assert gh_token not in out[0].content


class TestStreamCloudRedaction:
    @pytest.mark.asyncio
    async def test_secrets_never_reach_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _last_sent_texts(monkeypatch)
        from nova_ai.server.cloud_router import stream_cloud

        secret = "sk-test-1234567890abcdef"
        msgs = [Message(role=Role.USER, content=f"my key is {secret}")]
        chunks = [c async for c in stream_cloud("gpt-4o", msgs)]

        assert chunks == ["ok"]
        sent = captured[0][0]["content"]
        assert secret not in sent

    @pytest.mark.asyncio
    async def test_redact_can_be_disabled_explicitly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _last_sent_texts(monkeypatch)
        from nova_ai.server.cloud_router import stream_cloud

        secret = "sk-test-1234567890abcdef"
        msgs = [Message(role=Role.USER, content=f"my key is {secret}")]
        _ = [
            c async for c in stream_cloud("gpt-4o", msgs, redact=False)  # noqa: F841
        ]

        assert secret in captured[0][0]["content"]
