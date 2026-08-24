"""Tests for Slack Block Kit formatting (roadmap WS2).

Covers the pure-dict builders in ``slack_blocks`` and the ``blocks``
passthrough on ``SlackChannel.send`` — all offline, no slack_sdk needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nova_ai.channels.slack import SlackChannel
from nova_ai.channels.slack_blocks import (
    FOLLOWUP_ACTIONS,
    FOLLOWUP_PROMPTS,
    MAX_BLOCKS,
    actions_block,
    build_reply_blocks,
    inline_mrkdwn,
    markdown_to_blocks,
)


class TestInlineMrkdwn:
    def test_bold_and_strikethrough_converted(self) -> None:
        assert inline_mrkdwn("**hi** and ~~gone~~") == "*hi* and ~gone~"

    def test_links_use_slack_syntax(self) -> None:
        assert (
            inline_mrkdwn("[docs](https://example.com)")
            == "<https://example.com|docs>"
        )

    def test_display_math_removed_inline_math_unwrapped(self) -> None:
        text = "see $x^2$ plus $$\\int_0^1 f$$ end"
        out = inline_mrkdwn(text)
        assert "$$" not in out
        assert "x^2" in out

    def test_plain_text_unchanged(self) -> None:
        assert inline_mrkdwn("just words") == "just words"


class TestMarkdownToBlocks:
    def test_empty_and_whitespace_return_no_blocks(self) -> None:
        assert markdown_to_blocks("") == []
        assert markdown_to_blocks("   \n  ") == []

    def test_headers_become_header_blocks(self) -> None:
        blocks = markdown_to_blocks("# Title\n\nbody")
        assert blocks[0]["type"] == "header"
        assert blocks[0]["text"]["type"] == "plain_text"
        assert blocks[0]["text"]["text"] == "Title"
        assert any(
            b["type"] == "section" and "body" in b["text"]["text"]
            for b in blocks[1:]
        )

    def test_horizontal_rule_becomes_divider(self) -> None:
        blocks = markdown_to_blocks("above\n---\nbelow")
        types = [b["type"] for b in blocks]
        assert "divider" in types
        assert types.index("divider") == 1  # after "above", before "below"

    def test_code_fence_preserved_verbatim(self) -> None:
        md = "```python\ndef f():\n    return *1*\n```"
        blocks = markdown_to_blocks(md)
        assert len(blocks) == 1
        text = blocks[0]["text"]["text"]
        # Language tag stripped; content not mrkdwn-converted.
        assert "python" not in text.splitlines()[0]
        assert "def f():" in text
        assert "return *1*" in text  # asterisks untouched inside code

    def test_unterminated_fence_still_emits_code(self) -> None:
        blocks = markdown_to_blocks("```\nstill code")
        assert len(blocks) == 1
        assert "still code" in blocks[0]["text"]["text"]

    def test_long_paragraph_chunked_under_limit(self) -> None:
        md = ("line of prose here\n" * 400).strip()
        blocks = markdown_to_blocks(md)
        assert len(blocks) > 1
        for block in blocks:
            assert len(block["text"]["text"]) <= 3000
            assert block["type"] == "section"

    def test_block_count_capped_with_truncation_notice(self) -> None:
        # 60 headers → 60 header blocks > the 50-block Slack cap.
        md = "\n".join(f"# Heading {i}" for i in range(60))
        blocks = markdown_to_blocks(md)
        assert len(blocks) <= MAX_BLOCKS
        assert blocks[-1]["type"] == "context"
        assert "truncated" in blocks[-1]["elements"][0]["text"]

    def test_overlong_header_truncated(self) -> None:
        blocks = markdown_to_blocks("# " + "x" * 500)
        assert len(blocks[0]["text"]["text"]) <= 150


class TestBuildReplyBlocks:
    def test_short_plain_reply_returns_none(self) -> None:
        assert build_reply_blocks("Sure thing!") is None

    def test_short_structured_reply_gets_blocks(self) -> None:
        blocks = build_reply_blocks("- first\n- second")
        assert blocks is not None
        assert blocks[0]["type"] == "section"
        assert "- first" in blocks[0]["text"]["text"]

    def test_long_plain_reply_gets_blocks(self) -> None:
        # Long enough that chunking helps even without markup.
        blocks = build_reply_blocks("word " * 200)
        assert blocks is not None

    def test_empty_reply_returns_none(self) -> None:
        assert build_reply_blocks("") is None


class TestActionsBlock:
    def test_shape_and_cap(self) -> None:
        buttons = [(f"act_{i}", f"Button {i}") for i in range(8)]
        block = actions_block(buttons)
        assert block["type"] == "actions"
        assert len(block["elements"]) == 5
        assert block["elements"][0]["action_id"] == "act_0"
        assert block["elements"][0]["type"] == "button"

    def test_invalid_entries_dropped(self) -> None:
        assert actions_block([("", "no id"), ("id", ""), ("ok", "Fine")])[
            "elements"
        ] == [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Fine", "emoji": True},
                "action_id": "ok",
            }
        ]

    def test_empty_returns_none(self) -> None:
        assert actions_block([]) is None


class TestFollowupConsistency:
    def test_every_button_has_a_prompt(self) -> None:
        for action_id, _label in FOLLOWUP_ACTIONS:
            assert action_id in FOLLOWUP_PROMPTS
            assert FOLLOWUP_PROMPTS[action_id].strip()


class TestSendWithBlocks:
    def _mock_post(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        return mock_response

    def test_send_includes_blocks_alongside_text(self) -> None:
        ch = SlackChannel(bot_token="xoxb-test")
        blocks = [{"type": "divider"}]
        with patch(
            "httpx.post", return_value=self._mock_post()
        ) as mock_post:
            assert ch.send("C123", "fallback", blocks=blocks) is True
        payload = mock_post.call_args[1]["json"]
        assert payload["blocks"] == blocks
        assert payload["text"] == "fallback"

    def test_send_without_blocks_has_no_blocks_key(self) -> None:
        ch = SlackChannel(bot_token="xoxb-test")
        with patch("httpx.post", return_value=self._mock_post()) as mock_post:
            ch.send("C123", "plain")
        assert "blocks" not in mock_post.call_args[1]["json"]
