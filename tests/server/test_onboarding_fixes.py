"""First-run onboarding regression tests.

Covers failure modes surfaced by the fresh-clone onboarding audit:
- missing web UI used to return a bare 404 JSON with no guidance
- ``nova init`` used to destroy the existing config with no backup
- doctor should notice when the browser UI hasn't been built
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi", reason="nova_ai[server] not installed")


@pytest.fixture
def mock_engine():
    """Minimal mock engine (same shape as test_channel_routes)."""
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    return engine


@pytest.fixture
def client_no_static(mock_engine, tmp_path, monkeypatch):
    """TestClient whose static/ dir does not exist (fresh-clone state)."""
    from fastapi.testclient import TestClient

    import nova_ai.server.app as app_module

    empty = tmp_path / "static-empty"
    empty.mkdir()
    monkeypatch.setattr(app_module, "_static_dir", lambda: empty)

    app = app_module.create_app(mock_engine, "test-model")
    return TestClient(app)


class TestWebUiMissingFallback:
    def test_root_returns_friendly_html_when_ui_missing(self, client_no_static):
        """GET / without a built UI returns 200 + the build-it page."""
        resp = client_no_static.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        body = resp.text.lower()
        assert "npm run build" in body
        assert "nova chat" in body

    def test_unknown_route_also_gets_guidance(self, client_no_static):
        resp = client_no_static.get("/some/spa/route")
        assert resp.status_code == 200
        assert "npm run build" in resp.text


class TestInitBackup:
    def test_backup_created_and_restorable(self, tmp_path, monkeypatch):
        """nova init's helper must copy the old config aside, not delete it."""
        import nova_ai.cli.init_cmd as init_cmd

        cfg = tmp_path / "config.toml"
        cfg.write_text('[server]\nhost = "127.0.0.1"\n', encoding="utf-8")
        monkeypatch.setattr(init_cmd, "DEFAULT_CONFIG_PATH", cfg)
        monkeypatch.setattr(init_cmd, "DEFAULT_CONFIG_DIR", tmp_path)

        backup = init_cmd._backup_existing_config()
        assert backup is not None
        assert backup.exists()
        assert backup.name.startswith("config.toml.bak-")
        assert "127.0.0.1" in backup.read_text(encoding="utf-8")
        # Original untouched (init overwrites it afterwards, not the helper)
        assert cfg.exists()

    def test_backup_noop_when_missing(self, tmp_path, monkeypatch):
        import nova_ai.cli.init_cmd as init_cmd

        monkeypatch.setattr(
            init_cmd, "DEFAULT_CONFIG_PATH", tmp_path / "config.toml"
        )
        monkeypatch.setattr(init_cmd, "DEFAULT_CONFIG_DIR", tmp_path)
        assert init_cmd._backup_existing_config() is None

    def test_backup_pruning_keeps_five(self, tmp_path, monkeypatch):
        import nova_ai.cli.init_cmd as init_cmd

        cfg = tmp_path / "config.toml"
        cfg.write_text("x = 1\n", encoding="utf-8")
        monkeypatch.setattr(init_cmd, "DEFAULT_CONFIG_PATH", cfg)
        monkeypatch.setattr(init_cmd, "DEFAULT_CONFIG_DIR", tmp_path)
        for i in range(7):
            (tmp_path / f"config.toml.bak-2020010{i}-000000").write_text(
                f"bak{i}\n", encoding="utf-8"
            )
        init_cmd._backup_existing_config()
        remaining = sorted(tmp_path.glob("config.toml.bak-*"))
        # 7 pre-seeded + 1 new − pruned down to max_backups (5)
        assert len(remaining) == 5
        # Oldest three pruned; the 4th-original is now the oldest survivor.
        assert remaining[0].name.endswith("-20200103-000000")
        assert remaining[-1].name != "-20200100-000000"


class TestDoctorWebUiCheck:
    def _layout(self, tmp_path, *, with_frontend, with_index):
        """Build a fake repo root layout and return its path."""
        if with_frontend:
            (tmp_path / "frontend").mkdir()
        if with_index:
            index = tmp_path / "src" / "nova_ai" / "server" / "static" / "index.html"
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_text("<html></html>", encoding="utf-8")
        return tmp_path

    def test_warns_when_ui_missing(self, tmp_path):
        """Fresh source checkout without a built UI → warn with the fix."""
        import nova_ai.cli.doctor_cmd as doctor_cmd

        root = self._layout(tmp_path, with_frontend=True, with_index=False)
        result = doctor_cmd._check_web_ui(repo_root=root)
        assert result.status == "warn"
        assert "npm run build" in (result.details or "")

    def test_ok_when_index_present(self, tmp_path):
        import nova_ai.cli.doctor_cmd as doctor_cmd

        root = self._layout(tmp_path, with_frontend=True, with_index=True)
        result = doctor_cmd._check_web_ui(repo_root=root)
        assert result.status == "ok"
        assert "built" in result.message

    def test_ok_when_no_frontend_dir(self, tmp_path):
        """Installed-package layout (no frontend/ checkout) → bundled, ok."""
        import nova_ai.cli.doctor_cmd as doctor_cmd

        root = self._layout(tmp_path, with_frontend=False, with_index=False)
        result = doctor_cmd._check_web_ui(repo_root=root)
        assert result.status == "ok"
        assert "bundled" in result.message
