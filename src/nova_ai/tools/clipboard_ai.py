"""Clipboard AI tool — process, summarize, and translate clipboard content."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


def _get_clipboard_text() -> str:
    """Read text from clipboard safely."""
    try:
        import pyperclip  # type: ignore
        return pyperclip.paste() or ""
    except Exception:
        pass

    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        text = r.clipboard_get()
        r.destroy()
        return text or ""
    except Exception:
        pass
    return ""


def _set_clipboard_text(text: str) -> bool:
    """Write text to clipboard safely."""
    try:
        import pyperclip  # type: ignore
        pyperclip.copy(text)
        return True
    except Exception:
        pass
    return False


@ToolRegistry.register("clipboard_ai")
class ClipboardAITool(BaseTool):
    """Tool for processing text directly from the OS clipboard."""

    tool_id = "clipboard_ai"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="clipboard_ai",
            description=(
                "Read text from clipboard and perform an AI operation (summarize, translate, "
                "explain, fix_grammar, code_review, action_items)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["summarize", "translate", "explain", "fix_grammar", "code_review", "action_items"],
                        "description": "Operation to perform on the clipboard text.",
                        "default": "summarize",
                    },
                    "text": {
                        "type": "string",
                        "description": "Optional text to use instead of reading from clipboard.",
                    },
                    "language": {
                        "type": "string",
                        "description": "Target language if action is translate.",
                        "default": "English",
                    },
                    "copy_back": {
                        "type": "boolean",
                        "description": "Whether to copy the AI result back to clipboard.",
                        "default": False,
                    },
                },
                "required": ["action"],
            },
            category="productivity",
            timeout_seconds=30.0,
        )

    def execute(
        self,
        action: str = "summarize",
        text: Optional[str] = None,
        language: str = "English",
        copy_back: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        content = text or _get_clipboard_text()
        if not content.strip():
            return ToolResult(
                tool_name="clipboard_ai",
                content="Clipboard is empty or text is missing.",
                success=False,
            )

        prompts = {
            "summarize": f"Summarize the following text concisely in bullet points:\n\n{content}",
            "explain": f"Explain the following in simple and clear terms:\n\n{content}",
            "translate": f"Translate the following text accurately to {language}:\n\n{content}",
            "fix_grammar": f"Correct all grammar and spelling errors in the following text while maintaining tone:\n\n{content}",
            "code_review": f"Review the following code for bugs, performance issues, and best practices:\n\n{content}",
            "action_items": f"Extract all concrete action items and tasks from the following text as a checklist:\n\n{content}",
        }

        prompt = prompts.get(action, prompts["summarize"])

        try:
            from nova_ai.sdk import Nova
            result_text = Nova().ask(prompt)
        except Exception as exc:
            result_text = f"Error processing clipboard text: {exc}"

        if copy_back and result_text:
            _set_clipboard_text(result_text)

        return ToolResult(
            tool_name="clipboard_ai",
            content=result_text,
            success=True,
            metadata={
                "action": action,
                "input_length": len(content),
                "copied_back": copy_back,
            },
        )
