from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from nova_ai.tools.canvas_tool import CanvasTool


def test_canvas_spec() -> None:
    tool = CanvasTool()
    spec = tool.spec
    assert spec.name == "canvas"
    assert spec.category == "visualization"
    assert "title" in spec.parameters["required"]
    assert "html_body" in spec.parameters["required"]


@patch("nova_ai.tools.canvas_tool.webbrowser.open")
def test_canvas_execute_success(mock_open: MagicMock) -> None:
    with TemporaryDirectory() as tmpdir:
        with patch(
            "nova_ai.tools.canvas_tool._get_canvas_dir", return_value=Path(tmpdir)
        ):
            tool = CanvasTool()
            result = tool.execute(
                title="Revenue Chart",
                html_body="<svg><circle r='10' /></svg>",
                auto_open=True,
            )

            assert result.success is True
            assert "Revenue Chart" in result.content
            assert "artifact_id" in result.metadata
            file_path = Path(result.metadata["file_path"])
            assert file_path.exists()
            content = file_path.read_text(encoding="utf-8")
            assert "Revenue Chart" in content
            assert "<svg><circle r='10' /></svg>" in content
            mock_open.assert_called_once()
