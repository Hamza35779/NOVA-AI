"""Tests for ``nova connect`` CLI command."""

from __future__ import annotations

from unittest import mock

from click.testing import CliRunner

from nova_ai.cli import cli


def test_connect_list_no_connectors() -> None:
    """--list with an empty registry shows a 'no connectors' message."""
    runner = CliRunner()
    with mock.patch(
        "nova_ai.cli.connect_cmd.connect.__wrapped__"
        if hasattr(cli, "__wrapped__")
        else "nova_ai.core.registry.ConnectorRegistry.items",
        return_value=(),
    ):
        with mock.patch(
            "nova_ai.core.registry.ConnectorRegistry.items",
            return_value=(),
        ):
            result = runner.invoke(cli, ["connect", "--list"])

    assert result.exit_code == 0
    assert "No connectors registered" in result.output


def test_connect_list_with_connector(tmp_path: object) -> None:
    """--list with a connector registered shows it in the table."""
    runner = CliRunner()

    # Build a minimal mock connector class
    mock_cls = mock.MagicMock()
    mock_cls.auth_type = "filesystem"
    mock_instance = mock.MagicMock()
    mock_instance.is_connected.return_value = True
    mock_cls.return_value = mock_instance

    with mock.patch(
        "nova_ai.core.registry.ConnectorRegistry.items",
        return_value=(("obsidian", mock_cls),),
    ):
        result = runner.invoke(cli, ["connect", "--list"])

    assert result.exit_code == 0
    assert "obsidian" in result.output


def test_connect_help() -> None:
    """--help exits 0 and mentions the word 'connect'."""
    runner = CliRunner()
    result = runner.invoke(cli, ["connect", "--help"])
    assert result.exit_code == 0
    assert "connect" in result.output.lower()


def test_connect_specific_source(tmp_path: object) -> None:
    """connect --path /nonexistent obsidian shows an error gracefully."""
    runner = CliRunner()

    mock_cls = mock.MagicMock()
    mock_cls.auth_type = "filesystem"
    mock_instance = mock.MagicMock()
    # Path does not exist -> is_connected returns False
    mock_instance.is_connected.return_value = False
    mock_cls.return_value = mock_instance

    with (
        mock.patch(
            "nova_ai.core.registry.ConnectorRegistry.contains",
            return_value=True,
        ),
        mock.patch(
            "nova_ai.core.registry.ConnectorRegistry.get",
            return_value=mock_cls,
        ),
    ):
        # --path before the positional source arg (standard Click group behaviour)
        result = runner.invoke(cli, ["connect", "--path", "/nonexistent", "obsidian"])

    assert result.exit_code == 0
    # Should mention the source and give an indication something went wrong
    assert "obsidian" in result.output or "nonexistent" in result.output


def test_connect_disconnect() -> None:
    """--disconnect gmail exits 0."""
    runner = CliRunner()

    mock_cls = mock.MagicMock()
    mock_instance = mock.MagicMock()
    mock_cls.return_value = mock_instance

    with (
        mock.patch(
            "nova_ai.core.registry.ConnectorRegistry.contains",
            return_value=True,
        ),
        mock.patch(
            "nova_ai.core.registry.ConnectorRegistry.get",
            return_value=mock_cls,
        ),
    ):
        result = runner.invoke(cli, ["connect", "--disconnect", "gmail"])

    assert result.exit_code == 0
    mock_instance.disconnect.assert_called_once()


def test_connect_sync_single_source() -> None:
    """--sync <implicit all> runs SyncEngine for connected sources."""
    runner = CliRunner()

    mock_cls = mock.MagicMock()
    mock_instance = mock.MagicMock()
    mock_instance.is_connected.return_value = True
    mock_cls.return_value = mock_instance

    mock_engine = mock.MagicMock()
    mock_engine.sync.return_value = 3

    with (
        mock.patch("nova_ai.connectors.sync_engine.SyncEngine", return_value=mock_engine),
        mock.patch("nova_ai.connectors.store.KnowledgeStore"),
        mock.patch("nova_ai.connectors.pipeline.IngestionPipeline"),
        mock.patch(
            "nova_ai.core.registry.ConnectorRegistry.keys",
            return_value=["obsidian"],
        ),
        mock.patch(
            "nova_ai.core.registry.ConnectorRegistry.get",
            return_value=mock_cls,
        ),
        mock.patch(
            "nova_ai.core.registry.ConnectorRegistry.contains",
            return_value=True,
        ),
    ):
        result = runner.invoke(cli, ["connect", "--sync"])

    assert result.exit_code == 0, result.output
    assert "synced 3 item(s)" in result.output
    mock_engine.sync.assert_called_once_with(mock_instance)


def test_connect_sync_not_connected() -> None:
    """--sync on a disconnected source prints a hint instead of failing."""
    runner = CliRunner()

    mock_cls = mock.MagicMock()
    mock_instance = mock.MagicMock()
    mock_instance.is_connected.return_value = False
    mock_cls.return_value = mock_instance

    with (
        mock.patch("nova_ai.connectors.sync_engine.SyncEngine"),
        mock.patch("nova_ai.connectors.store.KnowledgeStore"),
        mock.patch("nova_ai.connectors.pipeline.IngestionPipeline"),
        mock.patch(
            "nova_ai.core.registry.ConnectorRegistry.keys",
            return_value=["obsidian"],
        ),
        mock.patch(
            "nova_ai.core.registry.ConnectorRegistry.get",
            return_value=mock_cls,
        ),
        mock.patch(
            "nova_ai.core.registry.ConnectorRegistry.items",
            return_value=(("obsidian", mock_cls),),
        ),
    ):
        result = runner.invoke(cli, ["connect", "--sync"])

    assert result.exit_code == 0, result.output
    assert "not connected" in result.output
