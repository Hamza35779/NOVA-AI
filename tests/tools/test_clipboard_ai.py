import pytest
from unittest.mock import patch, MagicMock
from nova_ai.tools.clipboard_ai import ClipboardAITool, _get_clipboard_text, _set_clipboard_text

def test_clipboard_ai_empty():
    with patch("nova_ai.tools.clipboard_ai._get_clipboard_text", return_value=""):
        tool = ClipboardAITool()
        res = tool.execute()
        assert res.success is False
        assert "Clipboard is empty" in res.content

@patch("nova_ai.sdk.Nova.ask")
def test_clipboard_ai_summarize(mock_ask):
    mock_ask.return_value = "Summary text"
    with patch("nova_ai.tools.clipboard_ai._get_clipboard_text", return_value="Some text to summarize"):
        tool = ClipboardAITool()
        res = tool.execute(action="summarize")
        assert res.success is True
        assert res.content == "Summary text"
        mock_ask.assert_called_once()

@patch("nova_ai.sdk.Nova.ask")
@patch("nova_ai.tools.clipboard_ai._set_clipboard_text")
def test_clipboard_ai_copy_back(mock_set_clip, mock_ask):
    mock_ask.return_value = "Fixed grammar"
    with patch("nova_ai.tools.clipboard_ai._get_clipboard_text", return_value="Bad text"):
        tool = ClipboardAITool()
        res = tool.execute(action="fix_grammar", copy_back=True)
        assert res.success is True
        mock_set_clip.assert_called_once_with("Fixed grammar")
