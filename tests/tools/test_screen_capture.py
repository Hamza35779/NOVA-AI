from __future__ import annotations

from unittest.mock import MagicMock, patch

from nova_ai.tools.screen_capture import ScreenCaptureTool
from nova_ai.tools.screen_monitor import ScreenMonitorTool


def test_screen_capture_spec_valid():
    tool = ScreenCaptureTool()
    spec = tool.spec
    assert spec.name == "screen_capture"
    assert spec.category == "perception"
    assert spec.requires_confirmation is True


def test_screen_capture_missing_deps():
    tool = ScreenCaptureTool()
    with patch.dict("sys.modules", {"mss": None}):
        result = tool.execute()
        assert result.success is False
        assert "mss" in result.content or "Pillow" in result.content


@patch("nova_ai.tools.screen_capture._capture_region")
@patch("nova_ai.tools.screen_capture._extract_text")
def test_screen_capture_returns_text(mock_extract, mock_capture):
    mock_capture.return_value = MagicMock(width=1920, height=1080)
    mock_extract.return_value = "Hello World"

    with patch.dict(
        "sys.modules",
        {"mss": MagicMock(), "PIL": MagicMock(), "pytesseract": MagicMock()},
    ):
        tool = ScreenCaptureTool()
        result = tool.execute(region="active_window", extract_text=True)

        assert result.success is True
        assert result.content == "Hello World"
        assert result.metadata["resolution"] == "1920x1080"
        mock_capture.assert_called_once_with("active_window")
        mock_extract.assert_called_once()


def test_screen_monitor_spec_valid():
    tool = ScreenMonitorTool()
    spec = tool.spec
    assert spec.name == "screen_monitor"
    assert spec.category == "perception"
    assert spec.requires_confirmation is True
    assert "interval_seconds" in spec.parameters["properties"]
