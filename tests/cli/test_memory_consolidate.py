"""Tests for ``nova memory consolidate`` CLI subcommand."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from nova_ai.cli import cli


@pytest.fixture()
def nova_home(tmp_path, monkeypatch):
    """Redirect DEFAULT_CONFIG_DIR (config + consolidation stores) to tmp."""
    import nova_ai.cli.memory_cmd as mem_cmd
    import nova_ai.core.config as config_mod
    import nova_ai.core.paths as paths_mod

    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(paths_mod, "get_config_dir", lambda: tmp_path)
    # mem_cmd._consolidation_root imports get_config_dir at call time from
    # nova_ai.core.paths — patch there too for safety.
    monkeypatch.setattr(
        mem_cmd, "_consolidation_root", lambda: tmp_path / "learning" / "consolidation"
    )
    return tmp_path


def _invoke(args):
    return CliRunner().invoke(cli, ["memory", "consolidate", *args])


class TestConsolidateRun:
    def test_run_disabled_exits_1(self, nova_home) -> None:
        result = _invoke(["run", "--foreground"])
        assert result.exit_code == 1
        assert "enabled is false" in result.output

    def test_run_foreground_executes_pipeline(
        self, nova_home, monkeypatch
    ) -> None:
        from nova_ai.core.config import ConsolidationConfig

        monkeypatch.setattr(
            "nova_ai.cli.memory_cmd._effective_consolidation_config",
            lambda: ConsolidationConfig(enabled=True),
        )
        captured: dict = {}
        fake_summary = {
            "status": "completed",
            "run_id": "consol_x",
            "facts_added": 2,
        }

        def fake_foreground(cfg):
            captured["cfg"] = cfg
            return fake_summary

        monkeypatch.setattr(
            "nova_ai.cli.memory_cmd._run_foreground", fake_foreground
        )
        result = _invoke(["run", "--foreground"])
        assert result.exit_code == 0, result.output
        assert captured["cfg"].enabled is True
        assert "completed" in result.output

    def test_run_background_spawns_child(self, nova_home, monkeypatch) -> None:
        from nova_ai.core.config import ConsolidationConfig

        monkeypatch.setattr(
            "nova_ai.cli.memory_cmd._effective_consolidation_config",
            lambda: ConsolidationConfig(enabled=True),
        )
        spawned: dict = {}

        def fake_spawn():
            spawned["called"] = True

        monkeypatch.setattr(
            "nova_ai.cli.memory_cmd._spawn_background", fake_spawn
        )
        result = _invoke(["run"])
        assert result.exit_code == 0, result.output
        assert spawned.get("called") is True
        assert "background" in result.output.lower()


class TestConsolidateStatus:
    def test_status_no_runs(self, nova_home) -> None:
        result = _invoke(["status"])
        assert result.exit_code == 0, result.output
        assert "No consolidation runs yet" in result.output

    def test_status_shows_latest_run(self, nova_home) -> None:
        import nova_ai.cli.memory_cmd as mem_cmd

        store = mem_cmd._run_store()
        try:
            store.start_run("consol_latest", trigger="scheduled")
            store.finish_run("consol_latest", status="completed",
                             summary={"facts_added": 4})
        finally:
            store.close()
        result = _invoke(["status"])
        assert result.exit_code == 0, result.output
        assert "consol_latest" in result.output
        assert "completed" in result.output
        assert "scheduled" in result.output


class TestConsolidateFacts:
    def test_facts_empty(self, nova_home) -> None:
        result = _invoke(["facts"])
        assert result.exit_code == 0, result.output
        assert "No facts distilled yet" in result.output

    def test_facts_lists_rows(self, nova_home) -> None:
        import nova_ai.cli.memory_cmd as mem_cmd

        store = mem_cmd._fact_store()
        try:
            store.add_fact("The user prefers dark mode", topic="style",
                           confidence=0.9)
        finally:
            store.close()
        result = _invoke(["facts"])
        assert result.exit_code == 0, result.output
        assert "The user prefers dark mode" in result.output
        assert "style" in result.output


class TestConsolidateForget:
    def test_forget_requires_id(self, nova_home) -> None:
        result = _invoke(["forget"])
        assert result.exit_code == 1

    def test_forget_missing_fact_exits_1(self, nova_home) -> None:
        result = _invoke(["forget", "fact_nope"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_forget_marks_fact(self, nova_home) -> None:
        import nova_ai.cli.memory_cmd as mem_cmd

        store = mem_cmd._fact_store()
        try:
            fid = store.add_fact("Forgettable fact")
        finally:
            store.close()
        result = _invoke(["forget", fid])
        assert result.exit_code == 0, result.output
        assert "forgotten" in result.output

        store = mem_cmd._fact_store()
        try:
            assert store.get_fact(fid)["status"] == "forgotten"
        finally:
            store.close()
