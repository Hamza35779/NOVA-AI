"""Tests for the ``nova conversation`` CLI group and the DPO train lane."""

from __future__ import annotations

from unittest import mock

import pytest
from click.testing import CliRunner

from nova_ai.cli import cli
from nova_ai.conversations.store import ConversationStore


@pytest.fixture()
def nova_home(tmp_path, monkeypatch):
    """Isolated NOVA home: patch every path the CLI reads."""
    from nova_ai.cli import conversation_cmd as conv_cmd
    from nova_ai.core import config as config_mod
    from nova_ai.core import paths as paths_mod

    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(paths_mod, "get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(conv_cmd, "_db_path", lambda: tmp_path / "conversations.db")
    return tmp_path


@pytest.fixture()
def seeded_store(nova_home):
    store = ConversationStore(nova_home / "conversations.db")
    conv = store.create_conversation("Seeded")
    root = store._conn.execute(
        "SELECT id FROM conv_nodes WHERE conversation_id=?",
        (conv["id"],),
    ).fetchone()[0]
    user = store.add_message(conv["id"], root, "user", "hello")
    a1 = store.add_message(conv["id"], user, "assistant", "left answer", model="m1")
    a2 = store.add_message(conv["id"], user, "assistant", "right answer", model="m2")
    yield store, conv["id"], user, a1, a2
    store.close()


class TestConversationCLI:
    def test_registered_in_top_level_cli(self) -> None:
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "conversation" in result.output

    def test_subcommands_in_help(self) -> None:
        result = CliRunner().invoke(cli, ["conversation", "--help"])
        assert result.exit_code == 0
        for sub in ("list", "show", "pick", "pairs"):
            assert sub in result.output

    def test_list_empty(self, nova_home) -> None:
        result = CliRunner().invoke(cli, ["conversation", "list"])
        assert result.exit_code == 0
        assert "No conversations" in result.output

    def test_list_seeded(self, seeded_store) -> None:
        result = CliRunner().invoke(cli, ["conversation", "list"])
        assert result.exit_code == 0
        assert "Seeded" in result.output

    def test_show_tree(self, seeded_store) -> None:
        store, conv_id, _user, _a1, _a2 = seeded_store
        result = CliRunner().invoke(cli, ["conversation", "show", conv_id])
        assert result.exit_code == 0
        assert "hello" in result.output
        assert "left answer" in result.output
        assert "right answer" in result.output

    def test_show_unknown_conversation(self, nova_home) -> None:
        result = CliRunner().invoke(cli, ["conversation", "show", "conv_nope"])
        assert result.exit_code == 1
        assert "Unknown conversation" in result.output

    def test_pick_records_pair(self, seeded_store) -> None:
        store, _conv_id, _user, _a1, a2 = seeded_store
        result = CliRunner().invoke(
            cli, ["conversation", "pick", a2, "--source", "fork"]
        )
        assert result.exit_code == 0
        assert store.count_preference_pairs() == 1
        pair = store.list_preference_pairs()[0]
        assert pair["chosen_id"] == a2
        assert pair["source"] == "fork"

    def test_pick_unknown_node(self, nova_home) -> None:
        result = CliRunner().invoke(cli, ["conversation", "pick", "node_nope"])
        assert result.exit_code == 1

    def test_pairs_empty(self, nova_home) -> None:
        result = CliRunner().invoke(cli, ["conversation", "pairs"])
        assert result.exit_code == 0
        assert "No preference pairs" in result.output

    def test_pairs_json(self, seeded_store) -> None:
        store, _conv_id, user, a1, a2 = seeded_store
        store.add_sibling_choice(
            store.get_node(a1)["conversation_id"], [], a1, [a2]
        )
        result = CliRunner().invoke(cli, ["conversation", "pairs", "--json"])
        assert result.exit_code == 0
        assert '"chosen_id"' in result.output


class TestTrainLane:
    def test_lane_option_present(self) -> None:
        result = CliRunner().invoke(cli, ["train", "run", "--help"])
        assert result.exit_code == 0
        assert "dpo" in result.output

    def test_dpo_lane_blocked_when_disabled(self, nova_home) -> None:
        from nova_ai.cli import train_cmd

        cfg = mock.MagicMock()
        cfg.enabled = True
        cfg.dpo_enabled = False
        learning_cfg = mock.MagicMock()
        learning_cfg.training_effective = cfg
        with mock.patch.object(
            train_cmd, "load_config", return_value=mock.MagicMock(learning=learning_cfg)
        ):
            result = CliRunner().invoke(cli, ["train", "run", "--lane", "dpo"])
        assert result.exit_code == 1
        assert "DPO preference lane is disabled" in result.output

    def test_dpo_lane_accepted_when_enabled(self, nova_home) -> None:
        from nova_ai.cli import train_cmd

        cfg = mock.MagicMock()
        cfg.enabled = True
        cfg.dpo_enabled = True
        cfg.auto_apply = False
        learning_cfg = mock.MagicMock()
        learning_cfg.training_effective = cfg
        learning_cfg.min_improvement = 0.02

        run_store = mock.MagicMock()
        run_store.is_running.return_value = False
        record = {"id": "r1", "status": "pending_review"}
        with mock.patch.object(
            train_cmd, "load_config", return_value=mock.MagicMock(learning=learning_cfg)
        ), mock.patch.object(
            train_cmd, "_run_store", return_value=run_store
        ), mock.patch.object(
            train_cmd, "_run_foreground", return_value=record
        ) as fg:
            result = CliRunner().invoke(cli, ["train", "run", "--lane", "dpo", "--foreground"])
        assert result.exit_code == 0
        assert fg.call_args.kwargs.get("lane") == "dpo"
