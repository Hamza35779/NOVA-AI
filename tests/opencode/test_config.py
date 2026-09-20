"""Tests for opencode config template, merge, detection, and installer."""

import json
import sys

import pytest

from nova_ai.opencode import config as oc


def test_build_config_provider_shape():
    cfg = oc.build_config(["qwen3:8b", "llama3.1:8b"], server_url="http://127.0.0.1:8000")
    provider = cfg["provider"]["nova-ai"]
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"]["baseURL"] == "http://127.0.0.1:8000/v1"
    assert provider["options"]["apiKey"] == "{env:NOVA_AI_API_KEY}"
    assert set(provider["models"]) == {"qwen3:8b", "llama3.1:8b"}
    assert cfg["model"] == "nova-ai/qwen3:8b"
    assert cfg["small_model"] == "nova-ai/qwen3:8b"
    assert cfg["mcp"]["nova-ai-tools"]["type"] == "local"
    assert "AGENTS.md" in cfg["instructions"]


def test_build_config_fallback_models():
    cfg = oc.build_config(None)
    assert cfg["model"] == "nova-ai/qwen3:8b"
    assert "qwen3:8b" in cfg["provider"]["nova-ai"]["models"]


def test_build_config_no_mcp():
    cfg = oc.build_config(["qwen3:8b"], with_mcp=False)
    assert "mcp" not in cfg


def test_merge_preserves_user_keys():
    existing = {
        "model": "anthropic/claude-sonnet-4-5",
        "provider": {"anthropic": {"options": {"apiKey": "{env:X}"}}},
        "permission": {"edit": "ask"},
    }
    generated = oc.build_config(["qwen3:8b"])
    merged = oc.merge_config(existing, generated)
    # User default model wins; NOVA provider added; unrelated keys intact.
    assert merged["model"] == "anthropic/claude-sonnet-4-5"
    assert "anthropic" in merged["provider"]
    assert "nova-ai" in merged["provider"]
    assert merged["permission"] == {"edit": "ask"}
    assert "nova-ai-tools" in merged["mcp"]


def test_merge_fills_missing_model():
    merged = oc.merge_config({}, oc.build_config(["qwen3:8b"]))
    assert merged["model"] == "nova-ai/qwen3:8b"
    assert merged["$schema"] == oc.SCHEMA_URL


def test_write_project_config_offline_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "fetch_server_models", lambda *a, **k: None)
    path, reachable, models = oc.write_project_config(tmp_path)
    assert path.name == "opencode.json"
    assert reachable is False
    assert models == ["qwen3:8b"]
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["provider"]["nova-ai"]["models"]["qwen3:8b"]


def test_write_project_config_creates_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "fetch_server_models", lambda *a, **k: ["qwen3:8b"])
    missing = tmp_path / "new" / "nested"
    path, reachable, _ = oc.write_project_config(missing)
    assert reachable is True
    assert path.is_file()


def test_write_project_config_live_models(tmp_path, monkeypatch):
    monkeypatch.setattr(
        oc, "fetch_server_models", lambda *a, **k: ["qwen3:8b", "phi4:14b"]
    )
    path, reachable, models = oc.write_project_config(tmp_path)
    assert reachable is True
    assert models == ["qwen3:8b", "phi4:14b"]
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["model"] == "nova-ai/qwen3:8b"


def test_write_preserves_existing_user_config(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "fetch_server_models", lambda *a, **k: ["qwen3:8b"])
    target = tmp_path / "opencode.json"
    target.write_text(
        json.dumps({"model": "openrouter/glm-5", "custom": {"a": 1}}),
        encoding="utf-8",
    )
    oc.write_project_config(tmp_path)
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["model"] == "openrouter/glm-5"
    assert on_disk["custom"] == {"a": 1}
    assert "nova-ai" in on_disk["provider"]


def test_nova_command_prefers_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/nova" if name == "nova" else None)
    assert oc.nova_command() == ["nova", "mcp", "serve"]


def test_nova_command_falls_back_to_module(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    cmd = oc.nova_command()
    assert cmd == [sys.executable, "-m", "nova_ai.cli", "mcp", "serve"]


def test_install_detects_existing(monkeypatch):
    monkeypatch.setattr(oc, "detect_opencode", lambda: "/usr/bin/opencode")
    monkeypatch.setattr(oc, "opencode_version", lambda exe=None: "1.18.30")
    ok, message = oc.install_opencode()
    assert ok is True
    assert "already installed" in message


def test_install_dry_run_without_binary(monkeypatch):
    monkeypatch.setattr(oc, "detect_opencode", lambda: None)
    ok, message = oc.install_opencode(dry_run=True)
    assert ok is False
    assert message.startswith("would run:")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only guidance path")
def test_install_no_toolchain_guidance(monkeypatch):
    monkeypatch.setattr(oc, "detect_opencode", lambda: None)
    monkeypatch.setattr("shutil.which", lambda name: None)
    ok, message = oc.install_opencode()
    assert ok is False
    assert "npm install -g opencode-ai" in message


def test_template_has_no_hardcoded_secrets():
    cfg = oc.build_config(["qwen3:8b"])
    blob = json.dumps(cfg)
    assert "sk-" not in blob
    assert cfg["provider"]["nova-ai"]["options"]["apiKey"] == "{env:NOVA_AI_API_KEY}"


def test_set_default_model(tmp_path):
    target = tmp_path / "opencode.json"
    target.write_text(json.dumps({"model": "anthropic/x"}), encoding="utf-8")
    ok, message = oc.set_default_model("phi4:14b", target)
    assert ok is True
    assert "nova-ai/phi4:14b" in message
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["model"] == "nova-ai/phi4:14b"
    assert on_disk["small_model"] == "nova-ai/phi4:14b"


def test_set_default_model_accepts_prefixed_id(tmp_path):
    target = tmp_path / "opencode.json"
    target.write_text("{}", encoding="utf-8")
    ok, _ = oc.set_default_model("nova-ai/qwen3:8b", target)
    assert ok is True
    assert json.loads(target.read_text(encoding="utf-8"))["model"] == "nova-ai/qwen3:8b"


def test_set_default_model_keeps_custom_small_model(tmp_path):
    target = tmp_path / "opencode.json"
    target.write_text(
        json.dumps({"model": "nova-ai/a", "small_model": "openrouter/glm-5"}),
        encoding="utf-8",
    )
    oc.set_default_model("phi4:14b", target)
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["model"] == "nova-ai/phi4:14b"
    assert on_disk["small_model"] == "openrouter/glm-5"


def test_list_and_current_model(tmp_path):
    target = tmp_path / "opencode.json"
    target.write_text(
        json.dumps(
            {
                "model": "nova-ai/qwen3:8b",
                "provider": {"nova-ai": {"models": {"qwen3:8b": {}, "phi4:14b": {}}}},
            }
        ),
        encoding="utf-8",
    )
    assert oc.list_configured_models(target) == ["qwen3:8b", "phi4:14b"]
    assert oc.current_default_model(target) == "nova-ai/qwen3:8b"
    assert oc.current_default_model(tmp_path / "missing.json") is None


def test_persist_env_var_windows(monkeypatch):
    import os

    monkeypatch.setattr(sys, "platform", "win32")
    calls = {}

    class FakeProc:
        returncode = 0

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return FakeProc()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    monkeypatch.delenv("NOVA_TEST_KEY_XYZ", raising=False)
    ok, message = oc.persist_env_var("NOVA_TEST_KEY_XYZ", "  secret123  ")
    assert ok is True
    assert calls["cmd"][:2] == ["setx", "NOVA_TEST_KEY_XYZ"]
    assert os.environ["NOVA_TEST_KEY_XYZ"] == "secret123"
    assert "future terminals" in message
    monkeypatch.delenv("NOVA_TEST_KEY_XYZ", raising=False)


def test_persist_env_var_posix(monkeypatch, tmp_path):

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.delenv("NOVA_TEST_KEY_XYZ", raising=False)
    # Path.home() must follow the monkeypatched HOME.
    monkeypatch.setattr(oc.Path, "home", classmethod(lambda cls: tmp_path))
    ok, _ = oc.persist_env_var("NOVA_TEST_KEY_XYZ", "abc")
    assert ok is True
    rc = tmp_path / ".bashrc"
    assert "export NOVA_TEST_KEY_XYZ='abc'" in rc.read_text(encoding="utf-8")
    # Second store replaces, never duplicates.
    oc.persist_env_var("NOVA_TEST_KEY_XYZ", "def")
    assert rc.read_text(encoding="utf-8").count("NOVA_TEST_KEY_XYZ") == 1
    monkeypatch.delenv("NOVA_TEST_KEY_XYZ", raising=False)


def test_persist_env_var_rejects_empty():
    ok, _ = oc.persist_env_var("NOVA_TEST_KEY_XYZ", "   ")
    assert ok is False


def test_server_health_rejects_foreign_port_squatter(monkeypatch):
    """A non-NOVA app answering /health must not count (live :8000 case)."""

    class FakeResp:
        def __init__(self, payload, status=200):
            self._payload = payload
            self.status = status

        def read(self):
            return json.dumps(self._payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(url, timeout=3.0):
        if url.endswith("/health"):
            return FakeResp({})
        return FakeResp({"info": {"title": "AI-Powered Business Decision Support"}})

    monkeypatch.setattr(oc.urllib.request, "urlopen", fake_urlopen)
    assert oc.server_health("http://127.0.0.1:8000") is False


def test_server_health_accepts_nova(monkeypatch):
    class FakeResp:
        def __init__(self, payload, status=200):
            self._payload = payload
            self.status = status

        def read(self):
            return json.dumps(self._payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(url, timeout=3.0):
        if url.endswith("/health"):
            return FakeResp({})
        return FakeResp({"info": {"title": "NOVA AI"}})

    monkeypatch.setattr(oc.urllib.request, "urlopen", fake_urlopen)
    assert oc.server_health("http://127.0.0.1:8000") is True


def test_build_config_local_only():
    cfg = oc.build_config(["qwen3:8b"], local_only=True)
    assert cfg["enabled_providers"] == ["nova-ai"]
    assert cfg["share"] == "disabled"


def test_build_config_default_not_local_only():
    cfg = oc.build_config(["qwen3:8b"])
    assert "enabled_providers" not in cfg
    assert "share" not in cfg


def test_merge_applies_local_only_slice():
    existing = {
        "model": "anthropic/x",
        "provider": {"anthropic": {}},
        "share": "manual",
    }
    merged = oc.merge_config(existing, oc.build_config(["qwen3:8b"], local_only=True))
    assert merged["enabled_providers"] == ["nova-ai"]
    assert merged["share"] == "disabled"
    # User's own providers/models survive the lock.
    assert "anthropic" in merged["provider"]
    assert merged["model"] == "anthropic/x"


def test_privacy_report_mixed_providers(tmp_path):
    target = tmp_path / "opencode.json"
    target.write_text(
        json.dumps(
            {
                "provider": {"nova-ai": {"models": {}}, "b.ai": {}},
                "disabled_providers": ["openrouter"],
                "share": "manual",
            }
        ),
        encoding="utf-8",
    )
    report = oc.privacy_report(target)
    by_id = {pid: (res, sel) for pid, res, sel in report["providers"]}
    assert by_id["nova-ai"] == ("local", True)
    assert by_id["b.ai"] == ("cloud", True)
    assert report["share"] == "manual"
    assert report["local_only"] is False


def test_privacy_report_local_only(tmp_path):
    target = tmp_path / "opencode.json"
    target.write_text(
        json.dumps(
            {
                "provider": {"nova-ai": {"models": {}}, "b.ai": {}},
                "enabled_providers": ["nova-ai"],
                "share": "disabled",
            }
        ),
        encoding="utf-8",
    )
    report = oc.privacy_report(target)
    by_id = {pid: (res, sel) for pid, res, sel in report["providers"]}
    assert by_id["b.ai"] == ("cloud", False)
    assert report["local_only"] is True
