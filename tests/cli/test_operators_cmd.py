"""Tests for the ``nova operators`` CLI commands."""

from __future__ import annotations

from unittest import mock

from click.testing import CliRunner

from nova_ai.cli import cli


def _patch_manager(health_rows=None):
    """Patch _build_system_with_operators to return mocked system/manager."""
    manager = mock.MagicMock()
    manager.health.return_value = health_rows or []

    config_patch = mock.patch(
        "nova_ai.core.config.load_config",
        return_value=mock.MagicMock(),
    )
    build_patch = mock.patch(
        "nova_ai.cli.operators_cmd._build_system_with_operators",
        return_value=(mock.MagicMock(), manager),
    )
    return config_patch, build_patch, manager


def _patch_store(runs):
    """Patch SchedulerStore used by the logs command."""
    store = mock.MagicMock()
    store.get_run_logs.return_value = runs

    return mock.patch(
        "nova_ai.scheduler.store.SchedulerStore",
        return_value=store,
    )


class TestOperatorsStatus:
    def test_status_renders_health_table(self) -> None:
        _, build_p, _ = _patch_manager(
            health_rows=[
                {
                    "id": "researcher",
                    "name": "Researcher",
                    "status": "active",
                    "health": "healthy",
                    "last_run": "2026-08-23T10:00:00+00:00",
                    "next_run": "2026-08-23T11:00:00+00:00",
                    "consecutive_failures": 0,
                    "recent_failures": 0,
                    "last_error": "",
                },
                {
                    "id": "monitor",
                    "name": "Monitor",
                    "status": "active",
                    "health": "failing",
                    "last_run": "2026-08-23T09:00:00+00:00",
                    "next_run": "2026-08-23T09:05:00+00:00",
                    "consecutive_failures": 4,
                    "recent_failures": 4,
                    "last_error": "engine unreachable",
                },
            ]
        )
        with build_p:
            result = CliRunner().invoke(cli, ["operators", "status"])

        assert result.exit_code == 0
        assert "researcher" in result.output
        assert "healthy" in result.output
        assert "failing" in result.output
        assert "Recent errors" in result.output
        assert "engine unreachable" in result.output

    def test_status_no_operators(self) -> None:
        _, build_p, _ = _patch_manager(health_rows=[])
        with build_p:
            result = CliRunner().invoke(cli, ["operators", "status"])

        assert result.exit_code == 0
        assert "No operators discovered" in result.output

    def test_status_listed_in_help(self) -> None:
        result = CliRunner().invoke(cli, ["operators", "--help"])
        assert result.exit_code == 0
        assert "status" in result.output


class TestOperatorsLogs:
    """Regression: the logs command must use SchedulerStore.get_run_logs.

    It previously called a nonexistent ``store.get_runs`` (only present on a
    test fake), so every invocation failed with an AttributeError.
    """

    def test_logs_uses_get_run_logs(self) -> None:
        runs = [
            {
                "started_at": "2026-08-23T10:00:00+00:00",
                "finished_at": "2026-08-23T10:00:05+00:00",
                "success": 1,
                "result": "Tick complete.",
                "error": "",
            }
        ]
        store_p = _patch_store(runs)
        with store_p, mock.patch("nova_ai.core.config.load_config") as cfg_p:
            cfg = mock.MagicMock()
            cfg.scheduler.db_path = ":memory:"
            cfg_p.return_value = cfg
            result = CliRunner().invoke(cli, ["operators", "logs", "my_op"])

        assert result.exit_code == 0
        assert "Tick complete." in result.output
        assert "Error:" not in result.output

    def test_logs_empty_history(self) -> None:
        store_p = _patch_store([])
        with store_p, mock.patch("nova_ai.core.config.load_config") as cfg_p:
            cfg = mock.MagicMock()
            cfg.scheduler.db_path = ":memory:"
            cfg_p.return_value = cfg
            result = CliRunner().invoke(cli, ["operators", "logs", "my_op"])

        assert result.exit_code == 0
        assert "No logs found" in result.output


class TestOperatorsInfo:
    def test_info_shows_guardrails(self) -> None:
        from nova_ai.operators.types import OperatorManifest

        manifest = OperatorManifest(
            id="guarded",
            name="Guarded",
            rate_limit_rpm=12,
            max_consecutive_failures=5,
            required_capabilities=["file:read"],
        )
        info_patch = mock.patch(
            "nova_ai.cli.operators_cmd._find_manifest",
            return_value=manifest,
        )
        with info_patch:
            result = CliRunner().invoke(cli, ["operators", "info", "guarded"])

        assert result.exit_code == 0
        assert "Required capabilities: file:read" in result.output
        assert "Rate limit: 12 runs/min" in result.output
        assert "Auto-pause after: 5 consecutive failures" in result.output
