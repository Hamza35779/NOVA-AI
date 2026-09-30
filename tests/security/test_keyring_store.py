"""Tests for the OS keyring secret store (audit item B3).

The real keyring backend is never touched: a fake module object replaces
the lazy ``_keyring()`` provider, and the ImportError path is exercised by
making the import fail.
"""

from __future__ import annotations

import pytest

from nova_ai.security import keyring_store


class _FakeModule:
    """Minimal stand-in for the ``keyring`` package."""

    def __init__(self) -> None:
        self.vault: dict[tuple[str, str], str] = {}
        self.fail = False
        self.fail_backend = False

    # -- backend probing ------------------------------------------------
    def get_keyring(self):  # noqa: ANN201
        if self.fail_backend:
            raise RuntimeError("backend exploded")

        class _Backend:
            __module__ = "tests.fake_backend"
            priority = 5

        return _Backend()

    # -- vault operations -------------------------------------------------
    def set_password(self, service: str, account: str, value: str) -> None:
        if self.fail:
            raise RuntimeError("vault locked")
        self.vault[(service, account)] = value

    def get_password(self, service: str, account: str):
        if self.fail:
            raise RuntimeError("vault locked")
        return self.vault.get((service, account))

    def delete_password(self, service: str, account: str) -> None:
        if self.fail:
            raise RuntimeError("vault locked")
        self.vault.pop((service, account), None)


@pytest.fixture()
def fake_keyring(monkeypatch):
    mod = _FakeModule()
    monkeypatch.setattr(keyring_store, "_keyring", lambda: mod)
    return mod


class TestStoreReadDelete:
    def test_round_trip(self, fake_keyring):
        keyring_store.store_secret("server", "api_key", "oj_sk_abc")
        assert keyring_store.read_secret("server", "api_key") == "oj_sk_abc"
        assert fake_keyring.vault == {("nova-ai", "server:api_key"): "oj_sk_abc"}

    def test_delete_returns_true_when_present(self, fake_keyring):
        keyring_store.store_secret("server", "api_key", "oj_sk_abc")
        assert keyring_store.delete_secret("server", "api_key") is True
        assert keyring_store.read_secret("server", "api_key") is None

    def test_delete_returns_false_when_absent(self, fake_keyring):
        assert keyring_store.delete_secret("server", "api_key") is False

    def test_backend_errors_propagate(self, fake_keyring):
        keyring_store.store_secret("server", "api_key", "oj_sk_abc")
        fake_keyring.fail = True
        with pytest.raises(RuntimeError, match="vault locked"):
            keyring_store.read_secret("server", "api_key")
        with pytest.raises(RuntimeError, match="vault locked"):
            keyring_store.delete_secret("server", "api_key")

    def test_scopes_are_namespaced(self, fake_keyring):
        keyring_store.store_secret("server", "api_key", "k1")
        keyring_store.store_secret("channels", "api_key", "k2")
        assert keyring_store.read_secret("server", "api_key") == "k1"
        assert keyring_store.read_secret("channels", "api_key") == "k2"


class TestAvailability:
    def test_available_with_healthy_backend(self, fake_keyring):
        assert keyring_store.keyring_available() is True

    def test_unavailable_when_backend_probe_fails(self, monkeypatch):
        mod = _FakeModule()
        mod.fail_backend = True
        monkeypatch.setattr(keyring_store, "_keyring", lambda: mod)
        assert keyring_store.keyring_available() is False

    def test_unavailable_when_package_missing(self, monkeypatch):
        real_import = (
            __builtins__["__import__"]
            if isinstance(__builtins__, dict)
            else __builtins__.__import__
        )

        def _no_keyring(name, *args, **kwargs):
            if name == "keyring":
                raise ImportError("no keyring here")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _no_keyring)
        assert keyring_store.keyring_available() is False
        with pytest.raises(keyring_store.KeyringUnavailable, match="security-keyring"):
            keyring_store.store_secret("server", "api_key", "x")


class TestNamespacing:
    def test_service_and_account_names(self, fake_keyring):
        keyring_store.store_secret("server", "api_key", "v")
        assert ("nova-ai", "server:api_key") in fake_keyring.vault
