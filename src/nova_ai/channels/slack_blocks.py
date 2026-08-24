"""Slack Block Kit builders — structured responses for Slack (roadmap WS2).

Pure-dict helpers with no ``slack_sdk`` dependency, so every Slack producer
(``SlackChannel`` and the Socket Mode daemon) can attach rich layouts
regardless of which optional extras are installed.  Callers always keep
sending the plain-mrkdwn ``text`` field alongside the blocks — Slack uses it
for notifications and as a fallback in surfaces that cannot render blocks.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "FOLLOWUP_ACTIONS",
    "FOLLOWUP_PROMPTS",
    "MAX_BLOCKS",
    "actions_block",
    "build_reply_blocks",
    "inline_mrkdwn",
    "markdown_to_blocks",
]

#: Slack rejects messages containing more than 50 blocks.
MAX_BLOCKS = 50

#: Slack caps section text at 3000 characters and header text at 150.
_SECTION_TEXT_LIMIT = 3000
_HEADER_TEXT_LIMIT = 150

#: Reply shorter than this with no structural markup renders fine as plain
#: mrkdwn — converting it to blocks buys nothing.
_PLAIN_TEXT_THRESHOLD = 400

_FENCE_RE = re.compile(r"^```(\w*)\s*$")
_HEADER_RE = re.compile(r"^#{1,6}\s+(.+)$")
_HR_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
_HAS_STRUCTURE_RE = re.compile(
    r"(?m)^(#{1,6}\s|\s*[-*+]\s|\s*\d+[.)]\s|```|_{3,}$|-{3,}$|\*{3,}$)"
)


def inline_mrkdwn(text: str) -> str:
    """Convert markdown inline markup to Slack mrkdwn."""
    # LaTeX: display math dropped entirely, inline math unwrapped —
    # Slack cannot render either.
    text = re.sub(r"\$\$.+?\$\$", "", text, flags=re.DOTALL)
    text = re.sub(r"\$(.+?)\$", r"\1", text)
    # Bold: **text** → *text*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    # Strikethrough: ~~text~~ → ~text~
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)
    # Links: [text](url) → <url|text>
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r"<\2|\1>", text)
    # Collapse excess blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_paragraph(text: str, limit: int) -> List[str]:
    """Split *text* into chunks of at most *limit* characters.

    Splits on line boundaries where possible; single lines longer than
    *limit* are hard-cut.
    """
    if len(text) <= limit:
        return [text]
    chunks: List[str] = []
    current: List[str] = []
    size = 0
    for line in text.split("\n"):
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        if current and size + len(line) + 1 > limit:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def markdown_to_blocks(markdown: str) -> List[Dict[str, Any]]:
    """Convert assistant markdown into a Block Kit layout.

    Headers become ``header`` blocks, horizontal rules become dividers,
    fenced code becomes its own verbatim mrkdwn section, and prose/list
    text is grouped into sections of at most 3000 characters.  Layouts are
    capped at Slack's 50-block limit with a trailing truncation notice.

    Returns an empty list for empty input; see :func:`build_reply_blocks`
    for the should-we-bother decision.
    """
    if not markdown or not markdown.strip():
        return []

    blocks: List[Dict[str, Any]] = []

    def _add_code(lines: List[str]) -> None:
        code = "\n".join(lines).strip("\n")
        if code:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"```\n{code}\n```"},
                }
            )

    para: List[str] = []
    in_code = False
    code_lines: List[str] = []

    def _flush_para() -> None:
        nonlocal para
        if not para:
            return
        text = inline_mrkdwn("\n".join(para))
        para = []
        if not text:
            return
        for chunk in _split_paragraph(text, _SECTION_TEXT_LIMIT):
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": chunk}}
            )

    for raw_line in markdown.split("\n"):
        fence = _FENCE_RE.match(raw_line.strip())
        if fence:
            if not in_code:
                in_code = True
                code_lines = []
                _flush_para()
            else:
                in_code = False
                _add_code(code_lines)
            continue
        if in_code:
            code_lines.append(raw_line)
            continue

        stripped = raw_line.strip()
        header = _HEADER_RE.match(stripped)
        if header:
            _flush_para()
            title = inline_mrkdwn(header.group(1))[:_HEADER_TEXT_LIMIT]
            if title:
                blocks.append(
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": title,
                            "emoji": True,
                        },
                    }
                )
            continue
        if _HR_RE.match(stripped):
            _flush_para()
            blocks.append({"type": "divider"})
            continue
        para.append(raw_line)

    # Unterminated fence: emit what was collected.
    if in_code:
        _add_code(code_lines)
    _flush_para()

    if len(blocks) > MAX_BLOCKS - 1:
        blocks = blocks[: MAX_BLOCKS - 1]
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "_Message truncated for Slack — open NOVA AI for the full answer._",
                    }
                ],
            }
        )
    return blocks


def build_reply_blocks(markdown: str) -> Optional[List[Dict[str, Any]]]:
    """Return layout blocks for *markdown*, or ``None`` for plain replies.

    Short messages without structural markup (no headers, lists, code
    fences, or rules) render better as a plain mrkdwn message; anything
    structured or long gets the Block Kit treatment.
    """
    if not markdown or not markdown.strip():
        return None
    if len(markdown) < _PLAIN_TEXT_THRESHOLD and not _HAS_STRUCTURE_RE.search(
        markdown
    ):
        return None
    return markdown_to_blocks(markdown) or None


def actions_block(
    buttons: List[Tuple[str, str]],
) -> Optional[Dict[str, Any]]:
    """Build an ``actions`` block of interactive buttons.

    Each entry is ``(action_id, label)``; at most five buttons are kept
    (Slack allows more, but rows beyond five wrap poorly).  Returns
    ``None`` when no valid entries remain.
    """
    cleaned = [(aid, label) for aid, label in buttons if aid and label][:5]
    if not cleaned:
        return None
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": label, "emoji": True},
                "action_id": action_id,
            }
            for action_id, label in cleaned
        ],
    }


#: Follow-up buttons attached to daemon research replies (roadmap WS2).
FOLLOWUP_ACTIONS: Tuple[Tuple[str, str], ...] = (
    ("nova_followup_summarize", "Summarize"),
    ("nova_followup_deeper", "Go deeper"),
    ("nova_followup_sources", "Sources"),
)

#: Prompts the daemon re-runs the agent with when a follow-up button is
#: clicked — keyed by the action_ids in :data:`FOLLOWUP_ACTIONS`.
FOLLOWUP_PROMPTS: Dict[str, str] = {
    "nova_followup_summarize": (
        "Summarize your previous answer as three concise bullet points."
    ),
    "nova_followup_deeper": (
        "Go deeper on your previous answer: expand the key points, add "
        "concrete examples, and note important caveats."
    ),
    "nova_followup_sources": (
        "List the sources you relied on for your previous answer, one per "
        "line, each as a markdown link."
    ),
}
