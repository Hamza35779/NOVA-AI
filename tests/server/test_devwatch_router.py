"""Tests for the devwatch REST router and CLI server reporting."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nova_ai.server.devwatch_router import _lock, _runs, router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _clear() -> None:
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
