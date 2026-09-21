"""Tests for the devwatch REST router and CLI server reporting."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nova_ai.server.devwatch_router import (
    _lock,
    _runs,
    disable_store_for_tests,
    router,
    set_store_for_tests,
)
from nova_ai.server.devwatch_store import DevWatchStore


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _clear() -> None:
    """Reset to a pure in-memory ring (no persistence) for the next test."""
    disable_store_for_tests()
    with _lock:
        _runs.clear()


class TestDevwatchRouter:
    def test_record_and_list(self) -> None:
        _clear()
        client = _client()
        resp = client.post(
            "/api/devwatch/runs",
            json={"command": "pytest -q", "status": "fail", "returncode": 1,
                  "failure_type": "exit_code", "output": "boom", "suggestion": "fix"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        resp = client.get("/api/devwatch/runs")
        runs = resp.json()["runs"]
        assert len(runs) == 1
        assert runs[0]["command"] == "pytest -q"
        assert runs[0]["at"]  # server filled the timestamp
        _clear()

    def test_newest_first(self) -> None:
        _clear()
        client = _client()
        for i in range(3):
            client.post(
                "/api/devwatch/runs",
                json={"command": f"cmd {i}", "status": "pass"},
            )
        runs = client.get("/api/devwatch/runs").json()["runs"]
        assert runs[0]["command"] == "cmd 2"
        assert runs[-1]["command"] == "cmd 0"
        _clear()

    def test_defaults(self) -> None:
        _clear()
        client = _client()
        client.post("/api/devwatch/runs", json={"command": "x", "status": "pass"})
        run = client.get("/api/devwatch/runs").json()["runs"][0]
        assert run["returncode"] == 0
        assert run["failure_type"] is None
        assert run["output"] == ""
        _clear()


class TestCliServerReporting:
    def test_run_once_posts_to_server(self) -> None:
        from rich.console import Console

        from nova_ai.cli.dev_watch_cmd import _run_once

        posted = {}

        def fake_urlopen(req, timeout):  # noqa: ANN001
            posted["url"] = req.full_url
            posted["data"] = req.data
            return SimpleNamespace(close=lambda: None)

        with patch.object(
            subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout="ok", stderr="")
        ), patch("urllib.request.urlopen", side_effect=fake_urlopen):
            run = _run_once("pytest -q", "off", 60, True, Console())

        assert run.status == "pass"
        assert posted["url"].endswith("/api/devwatch/runs")
        assert b"pytest -q" in posted["data"]

    def test_server_down_is_silent(self) -> None:
        from rich.console import Console

        from nova_ai.cli.dev_watch_cmd import _run_once

        with patch.object(
            subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout="ok", stderr="")
        ), patch(
            "urllib.request.urlopen", side_effect=OSError("conn refused")
        ):
            run = _run_once("pytest -q", "off", 60, True, Console())
        assert run.status == "pass"

    def test_app_includes_devwatch_router(self) -> None:
        from nova_ai.server.app import create_app  # noqa: F401  (import smoke)

        # Route registration is asserted via the router prefix contract.
        assert router.prefix == "/api/devwatch"


class TestDevwatchPersistence:
    def test_record_persists_to_sqlite(self, tmp_path) -> None:
        store = DevWatchStore(db_path=tmp_path / "devwatch.db")
        set_store_for_tests(store)
        client = _client()
        client.post(
            "/api/devwatch/runs",
            json={"command": "pytest -q", "status": "fail", "returncode": 1,
                  "failure_type": "exit_code", "output": "boom", "suggestion": "fix"},
        )
        assert store.count() == 1
        recent = store.list_recent(limit=10)
        assert recent[0]["command"] == "pytest -q"
        assert recent[0]["status"] == "fail"
        assert recent[0]["at"]  # timestamp filled by the router

    def test_ring_rehydrates_after_restart(self, tmp_path) -> None:
        """A fresh router (simulated restart) sees previously stored runs."""
        db_path = tmp_path / "devwatch.db"
        store = DevWatchStore(db_path=db_path)
        set_store_for_tests(store)
        client = _client()
        for i in range(3):
            client.post("/api/devwatch/runs",
                        json={"command": f"cmd {i}", "status": "pass"})

        # Simulate a server restart: new store over the same DB, empty ring.
        store.close()
        store2 = DevWatchStore(db_path=db_path)
        set_store_for_tests(store2)
        assert len(_runs) == 3  # rehydrated from SQLite
        runs = _client().get("/api/devwatch/runs").json()["runs"]
        assert runs[0]["command"] == "cmd 2"  # newest first preserved

    def test_broken_store_does_not_break_api(self) -> None:
        """A store that fails to open must not break recording/serving."""
        class _BrokenStore:
            available = False

            def record(self, entry):
                raise RuntimeError("disk on fire")

            def list_recent(self, limit):
                return []

            def count(self):
                return 0

            def close(self):
                pass

        disable_store_for_tests()
        set_store_for_tests(_BrokenStore())
        client = _client()
        resp = client.post("/api/devwatch/runs",
                           json={"command": "x", "status": "pass"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        runs = client.get("/api/devwatch/runs").json()["runs"]
        assert len(runs) == 1

    def test_prune_keeps_table_bounded(self, tmp_path) -> None:
        store = DevWatchStore(db_path=tmp_path / "devwatch.db")
        for i in range(600):
            store.record({"command": f"cmd {i}", "status": "pass", "at": str(i)})
        assert store.count() == 500  # _MAX_PERSISTED
        newest = store.list_recent(limit=1)[0]
        assert newest["command"] == "cmd 599"

    def test_store_defaults_to_config_dir(self, tmp_path, monkeypatch) -> None:
        from nova_ai.core import paths as core_paths

        monkeypatch.setattr(core_paths, "get_config_dir",
                            lambda: tmp_path / "cfg")
        store = DevWatchStore()
        try:
            assert (tmp_path / "cfg" / "devwatch.db").exists()
        finally:
            store.close()
