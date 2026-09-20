"""Tests for `nova mcp` and `nova opencode` CLI commands."""

import json
import sys

from click.testing import CliRunner

from nova_ai.cli import cli
from nova_ai.cli.mcp_cmd import mcp
from nova_ai.cli.opencode_cmd import opencode
from nova_ai.opencode import config as oc


def test_mcp_registered_on_cli():
    result = CliRunner().invoke(cli, ["mcp", "--help"])
    assert result.exit_code == 0
    assert "serve" in result.output


def test_opencode_registered_on_cli():
    result = CliRunner().invoke(cli, ["opencode", "--help"])
    assert result.exit_code == 0
    for sub in ("status", "install", "init", "launch", "model", "setup"):
        assert sub in result.output


def test_mcp_tools_lists():
    result = CliRunner().invoke(mcp, ["tools"])
    assert result.exit_code == 0
    assert "calculator" in result.output


def test_opencode_status_offline(monkeypatch, tmp_path):
    monkeypatch.setattr(oc, "detect_opencode", lambda: None)
    monkeypatch.setattr(oc, "server_health", lambda *a, **k: False)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(opencode, ["status"])
    assert result.exit_code == 0
    assert "missing" in result.output


def test_opencode_install_dry_run(monkeypatch):
    monkeypatch.setattr(oc, "detect_opencode", lambda: None)
    result = CliRunner().invoke(opencode, ["install", "--dry-run"])
    assert result.exit_code == 0
    assert "would run" in result.output


def test_opencode_init_writes_config(monkeypatch, tmp_path):
    monkeypatch.setattr(oc, "fetch_server_models", lambda *a, **k: ["qwen3:8b"])
    result = CliRunner().invoke(opencode, ["init", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    on_disk = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert on_disk["provider"]["nova-ai"]["options"]["baseURL"].endswith("/v1")


def test_opencode_init_offline_warns(monkeypatch, tmp_path):
    monkeypatch.setattr(oc, "fetch_server_models", lambda *a, **k: None)
    result = CliRunner().invoke(opencode, ["init", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "unreachable" in result.output


def test_opencode_launch_requires_binary(monkeypatch):
    monkeypatch.setattr(oc, "detect_opencode", lambda: None)
    result = CliRunner().invoke(opencode, ["launch"])
    assert result.exit_code == 1
    assert "install" in result.output


def test_opencode_model_list(monkeypatch, tmp_path):
    monkeypatch.setattr(oc, "fetch_server_models", lambda *a, **k: ["qwen3:8b", "phi4:14b"])
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(opencode, ["model", "--list"])
    assert result.exit_code == 0
    assert "nova-ai/qwen3:8b" in result.output
    assert "nova-ai/phi4:14b" in result.output


def test_opencode_model_set_direct(monkeypatch, tmp_path):
    monkeypatch.setattr(oc, "fetch_server_models", lambda *a, **k: ["qwen3:8b"])
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(opencode, ["model", "qwen3:8b"])
    assert result.exit_code == 0
    assert "nova-ai/qwen3:8b" in result.output


def test_opencode_model_interactive_pick(monkeypatch, tmp_path):
    monkeypatch.setattr(
        oc, "fetch_server_models", lambda *a, **k: ["qwen3:8b", "phi4:14b"]
    )
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(opencode, ["model"], input="2\n")
    assert result.exit_code == 0
    assert "nova-ai/phi4:14b" in result.output


def test_opencode_setup_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(oc, "detect_opencode", lambda: "/usr/bin/opencode")
    monkeypatch.setattr(oc, "opencode_version", lambda exe=None: "1.18.30")
    monkeypatch.setattr(oc, "fetch_server_models", lambda *a, **k: ["qwen3:8b"])
    monkeypatch.setattr(oc, "server_health", lambda *a, **k: True)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(opencode, ["setup"], input="1\n")
    assert result.exit_code == 0
    assert "Setup complete" in result.output


def test_opencode_set_key_stores_env(monkeypatch, tmp_path):
    import os

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(oc.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("B_AI_API_KEY", raising=False)
    result = CliRunner().invoke(opencode, ["set-key", "b.ai"], input="newkey123\nnewkey123\n")
    assert result.exit_code == 0
    assert os.environ["B_AI_API_KEY"] == "newkey123"
    assert "revoke" in result.output  # rotation reminder for b.ai
    monkeypatch.delenv("B_AI_API_KEY", raising=False)


def test_opencode_set_key_unknown_provider():
    result = CliRunner().invoke(opencode, ["set-key", "nope"])
    assert result.exit_code == 1
    assert "Unknown provider" in result.output


def test_opencode_init_local_only(monkeypatch, tmp_path):
    monkeypatch.setattr(oc, "fetch_server_models", lambda *a, **k: None)
    result = CliRunner().invoke(opencode, ["init", "--local-only", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Local-only" in result.output
    on_disk = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert on_disk["enabled_providers"] == ["nova-ai"]
    assert on_disk["share"] == "disabled"


def test_opencode_status_privacy_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(oc, "detect_opencode", lambda: "/usr/bin/opencode")
    monkeypatch.setattr(oc, "opencode_version", lambda exe=None: "9.9.9")
    monkeypatch.setattr(oc, "server_health", lambda *a, **k: False)
    (tmp_path / "opencode.json").write_text(
        json.dumps({"provider": {"nova-ai": {"models": {}}}}), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(opencode, ["status"])
    assert result.exit_code == 0
    assert "never leaves this machine" in result.output
    assert "Sharing" in result.output


def test_connect_opencode_wizard_yes(monkeypatch, tmp_path):
    from nova_ai.cli.connect_cmd import connect

    monkeypatch.setattr(oc, "detect_opencode", lambda: "/usr/bin/opencode")
    monkeypatch.setattr(oc, "opencode_version", lambda exe=None: "1.18.30")
    monkeypatch.setattr(oc, "fetch_server_models", lambda *a, **k: ["qwen3:8b"])
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(connect, ["--yes", "opencode"])
    assert result.exit_code == 0
    assert "opencode CLI" in result.output
    assert (tmp_path / "opencode.json").is_file()


def test_connect_opencode_wizard_model_flag(monkeypatch, tmp_path):
    from nova_ai.cli.connect_cmd import connect

    monkeypatch.setattr(oc, "detect_opencode", lambda: "/usr/bin/opencode")
    monkeypatch.setattr(oc, "opencode_version", lambda exe=None: "1.18.30")
    monkeypatch.setattr(oc, "fetch_server_models", lambda *a, **k: ["qwen3:8b", "phi4:14b"])
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(connect, ["--yes", "--model", "phi4:14b", "opencode"])
    assert result.exit_code == 0
    assert "nova-ai/phi4:14b" in result.output


def test_connect_unknown_source_hint_mentions_opencode():
    from nova_ai.cli.connect_cmd import connect

    result = CliRunner().invoke(connect, ["definitely-not-a-source"])
    assert "opencode" in result.output
