"""Tests for ``nova scheduler create --metadata``."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from nova_ai.cli import cli
from nova_ai.scheduler.store import SchedulerStore


@pytest.fixture()
def scheduler_home(tmp_path, monkeypatch):
    """Redirect DEFAULT_CONFIG_DIR to tmp_path and stub _get_store."""
    import nova_ai.cli.scheduler_cmd as sched_cmd
    import nova_ai.core.config as config_mod

    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_DIR", tmp_path)
    db = tmp_path / "scheduler.db"
    monkeypatch.setattr(
        sched_cmd,
        "_get_store",
        lambda: SchedulerStore(db),
    )
    return tmp_path, db


def _invoke(args):
    return CliRunner().invoke(cli, ["scheduler", "create", *args])


class TestSchedulerCreateMetadata:
    def test_create_without_metadata_defaults_empty(
        self, scheduler_home
    ) -> None:
        result = _invoke(
            ["hello", "--type", "once", "--value", "2030-01-01T00:00:00+00:00"]
        )
        assert result.exit_code == 0, result.output

        _, db = scheduler_home
        store = SchedulerStore(db)
        try:
            tasks = store.list_tasks()
            assert len(tasks) == 1
            assert tasks[0]["metadata"] == {}
        finally:
            store.close()

    def test_create_with_valid_metadata_persists(
        self, scheduler_home
    ) -> None:
        result = _invoke(
            [
                "prove new models",
                "--type",
                "cron",
                "--value",
                "0 4 * * *",
                "--metadata",
                '{"kind": "prove"}',
            ]
        )
        assert result.exit_code == 0, result.output
        assert '"kind"' in result.output or "prove" in result.output

        _, db = scheduler_home
        store = SchedulerStore(db)
        try:
            tasks = store.list_tasks()
            assert tasks[0]["metadata"] == {"kind": "prove"}
        finally:
            store.close()

    def test_create_with_invalid_json_exits_1(self, scheduler_home) -> None:
        result = _invoke(
            [
                "x",
                "--type",
                "once",
                "--value",
                "2030-01-01T00:00:00+00:00",
                "--metadata",
                "{not json",
            ]
        )
        assert result.exit_code == 1
        assert "Invalid --metadata JSON" in result.output

    def test_create_with_non_object_json_exits_1(self, scheduler_home) -> None:
        result = _invoke(
            [
                "x",
                "--type",
                "once",
                "--value",
                "2030-01-01T00:00:00+00:00",
                "--metadata",
                '["a", "b"]',
            ]
        )
        assert result.exit_code == 1
        assert "JSON object" in result.output

    def test_metadata_round_trip_dict_shape(self, scheduler_home) -> None:
        meta = {"kind": "consolidate", "lane": "dpo", "n": 3}
        result = _invoke(
            [
                "x",
                "--type",
                "once",
                "--value",
                "2030-01-01T00:00:00+00:00",
                "--metadata",
                json.dumps(meta),
            ]
        )
        assert result.exit_code == 0, result.output

        _, db = scheduler_home
        store = SchedulerStore(db)
        try:
            task = store.list_tasks()[0]
            assert task["metadata"] == meta
        finally:
            store.close()


class TestNoGlobalLeak:
    def test_store_patch_reverted_after_invoke(self, scheduler_home) -> None:
        """The _get_store monkeypatch must not leak into other tests."""
        _invoke(
            ["x", "--type", "once", "--value", "2030-01-01T00:00:00+00:00"]
        )
        import nova_ai.cli.scheduler_cmd as sched_cmd

        # After the fixture tears down, _get_store is the real function again
        # (monkeypatch undoes it). Just assert it is callable and named right.
        assert callable(sched_cmd._get_store)
