"""Tests for keyring-backed API key management (audit item B3).

Covers ``nova auth create-key --store keyring``, ``revoke-key`` clearing
both stores, ``migrate-key`` moving the key out of config.toml, and the
serve-side resolution order (env → keyring → config).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nova_ai.cli import cli  # noqa: E402
from nova_ai.cli.serve import _resolve_serve_api_key  # noqa: E402
from nova_ai.security import keyring_store  # noqa: E402


@pytest.fixture()
def fake_keyring(monkeypatch):
    """Swap the lazy keyring provider for an in-memory vault.

    Patching ``_keyring`` (instead of the public functions) keeps the real
    store/read/delete logic — including the ``nova-ai`` service namespacing
    — under test.
    """
    vault: dict[tuple[str, str], str] = {}

    class _FakeKeyringModule:
        def set_password(self, service: str, account: str, value: str) -> None:
            vault[(service, account)] = value

        def get_password(self, service: str, account: str):
            return vault.get((service, account))

        def delete_password(self, service: str, account: str) -> None:
            vault.pop((service, account), None)

    fake = _FakeKeyringModule()
    monkeypatch.setattr(keyring_store, "_keyring", lambda: fake)
    return vault


@pytest.fixture()
def isolated_config(monkeypatch, tmp_path):
    """Redirect DEFAULT_CONFIG_PATH/DIR to a temp dir."""
    import nova_ai.cli.auth_cmd as auth_mod

    cfg_dir = tmp_path / "home"
    cfg_path = cfg_dir / "config.toml"
    monkeypatch.setattr(auth_mod, "DEFAULT_CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(auth_mod, "DEFAULT_CONFIG_PATH", cfg_path)
    return cfg_path


class TestCreateKey:
    def test_keyring_store_keeps_config_clean(
        self, fake_keyring, isolated_config, monkeypatch, tmp_path
    ):
        # create-key uses module constants patched above; get_config_dir is
        # also consulted by migrate-key, so pin NOVA_AI_HOME for consistency.
        monkeypatch.setenv("NOVA_AI_HOME", str(tmp_path / "home2"))

        result = CliRunner().invoke(cli, ["auth", "create-key", "--store", "keyring"])
        assert result.exit_code == 0, result.output
        assert "OS keyring" in result.output
        assert ("nova-ai", "server:api_key") in fake_keyring
        assert not isolated_config.exists()  # nothing written to disk

    def test_config_store_still_writes_toml(self, fake_keyring, isolated_config):
        result = CliRunner().invoke(cli, ["auth", "create-key"])
        assert result.exit_code == 0, result.output
        assert "Stored in" in result.output
        assert fake_keyring == {}  # keyring untouched
        assert 'api_key = "oj_sk_' in isolated_config.read_text(encoding="utf-8")

    def test_keyring_unavailable_fails_cleanly(self, monkeypatch, isolated_config):
        def _boom(scope, key, value):
            raise keyring_store.KeyringUnavailable("extra not installed")

        monkeypatch.setattr(keyring_store, "store_secret", _boom)
        result = CliRunner().invoke(cli, ["auth", "create-key", "--store", "keyring"])
        assert result.exit_code == 1
        assert "unavailable" in result.output.lower()


class TestRevokeKey:
    def test_revokes_keyring_key(
        self, fake_keyring, isolated_config, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("NOVA_AI_HOME", str(tmp_path / "home2"))
        keyring_store.store_secret("server", "api_key", "oj_sk_live")

        result = CliRunner().invoke(cli, ["auth", "revoke-key"])
        assert result.exit_code == 0, result.output
        assert "keyring" in result.output
        assert ("nova-ai", "server:api_key") not in fake_keyring

    def test_revokes_plaintext_key(self, fake_keyring, isolated_config):
        isolated_config.parent.mkdir(parents=True, exist_ok=True)
        isolated_config.write_text(
            '[server]\nhost = "127.0.0.1"\n\n[server.auth]\napi_key = "oj_sk_old"\n',
            encoding="utf-8",
        )

        result = CliRunner().invoke(cli, ["auth", "revoke-key"])
        assert result.exit_code == 0, result.output
        assert "revoked" in result.output.lower()
        assert 'api_key = ""' in isolated_config.read_text(encoding="utf-8")

    def test_revokes_both(self, fake_keyring, isolated_config):
        isolated_config.parent.mkdir(parents=True, exist_ok=True)
        isolated_config.write_text(
            '[server.auth]\napi_key = "oj_sk_old"\n', encoding="utf-8"
        )
        keyring_store.store_secret("server", "api_key", "oj_sk_live")

        result = CliRunner().invoke(cli, ["auth", "revoke-key"])
        assert result.exit_code == 0, result.output
        assert ("nova-ai", "server:api_key") not in fake_keyring
        assert 'api_key = ""' in isolated_config.read_text(encoding="utf-8")

    def test_revokes_nothing(self, fake_keyring, isolated_config):
        result = CliRunner().invoke(cli, ["auth", "revoke-key"])
        assert result.exit_code == 0, result.output
        assert "No API key found" in result.output


class TestMigrateKey:
    def test_moves_key_from_config_to_keyring(
        self, fake_keyring, isolated_config, monkeypatch, tmp_path
    ):
        isolated_config.parent.mkdir(parents=True, exist_ok=True)
        isolated_config.write_text(
            '[server]\nhost = "127.0.0.1"\n\n[server.auth]\napi_key = "oj_sk_move"\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("NOVA_AI_HOME", str(tmp_path / "home2"))

        result = CliRunner().invoke(cli, ["auth", "migrate-key"])
        assert result.exit_code == 0, result.output
        assert fake_keyring[("nova-ai", "server:api_key")] == "oj_sk_move"
        text = isolated_config.read_text(encoding="utf-8")
        assert 'api_key = ""' in text
        assert "oj_sk_move" not in text
        # Other config content preserved
        assert 'host = "127.0.0.1"' in text

    def test_nothing_to_migrate(self, fake_keyring, isolated_config):
        isolated_config.parent.mkdir(parents=True, exist_ok=True)
        isolated_config.write_text('[server]\nhost = "127.0.0.1"\n', encoding="utf-8")
        result = CliRunner().invoke(cli, ["auth", "migrate-key"])
        assert result.exit_code == 0, result.output
        assert "nothing to migrate" in result.output.lower()
        assert fake_keyring == {}

    def test_keyring_unavailable_leaves_config_untouched(
        self, monkeypatch, isolated_config
    ):
        isolated_config.parent.mkdir(parents=True, exist_ok=True)
        isolated_config.write_text(
            '[server.auth]\napi_key = "oj_sk_keep"\n', encoding="utf-8"
        )

        def _boom(scope, key, value):
            raise keyring_store.KeyringUnavailable("no backend")

        monkeypatch.setattr(keyring_store, "store_secret", _boom)
        result = CliRunner().invoke(cli, ["auth", "migrate-key"])
        assert result.exit_code == 1
        assert 'api_key = "oj_sk_keep"' in isolated_config.read_text(encoding="utf-8")


class TestServeResolutionOrder:
    def _config_file(self, tmp_path, key=""):
        p = tmp_path / "config.toml"
        p.write_text(f'[server.auth]\napi_key = "{key}"\n', encoding="utf-8")
        return p

    def test_env_var_wins(self, tmp_path, fake_keyring):
        keyring_store.store_secret("server", "api_key", "oj_sk_kr")
        assert (
            _resolve_serve_api_key("oj_sk_env", self._config_file(tmp_path, "cfg"))
            == "oj_sk_env"
        )

    def test_keyring_before_config(self, tmp_path, fake_keyring):
        keyring_store.store_secret("server", "api_key", "oj_sk_kr")
        assert (
            _resolve_serve_api_key("", self._config_file(tmp_path, "oj_sk_cfg"))
            == "oj_sk_kr"
        )

    def test_falls_back_to_config(self, tmp_path, fake_keyring):
        assert (
            _resolve_serve_api_key("", self._config_file(tmp_path, "oj_sk_cfg"))
            == "oj_sk_cfg"
        )

    def test_all_empty(self, tmp_path, fake_keyring):
        assert _resolve_serve_api_key("", self._config_file(tmp_path)) == ""

    def test_broken_keyring_still_reads_config(self, tmp_path, monkeypatch):
        def _boom(scope, key):
            raise RuntimeError("vault locked")

        monkeypatch.setattr(keyring_store, "read_secret", _boom)
        assert (
            _resolve_serve_api_key("", self._config_file(tmp_path, "oj_sk_cfg"))
            == "oj_sk_cfg"
        )
