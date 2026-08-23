from __future__ import annotations

from unittest.mock import MagicMock, patch

from nova_ai.tools.cli_bridge import CLIBridgeTool


def test_cli_bridge_spec() -> None:
    tool = CLIBridgeTool()
    assert tool.spec.name == "cli_agent_bridge"
    assert "claude" in tool.spec.parameters["properties"]["cli_name"]["enum"]


def test_cli_bridge_missing_binary() -> None:
    tool = CLIBridgeTool()
    with patch("shutil.which", return_value=None):
        res = tool.execute(cli_name="claude", prompt="build feature")
        assert res.success is False
        assert "not found on system PATH" in res.content


def test_cli_bridge_success() -> None:
    tool = CLIBridgeTool()
    with (
        patch("shutil.which", return_value="/usr/local/bin/claude"),
        patch("subprocess.run") as mock_run,
    ):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Created file src/app.py"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        res = tool.execute(cli_name="claude", prompt="build feature")
        assert res.success is True
        assert "Created file src/app.py" in res.content
