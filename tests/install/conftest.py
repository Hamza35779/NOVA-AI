"""Test fixtures for installer / cold-start refresh tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_nova_ai_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``DEFAULT_CONFIG_DIR`` at a tmpdir for isolated tests.

    Returns the directory; teardown is automatic via tmp_path.
    """
    home = tmp_path / ".nova_ai"
    home.mkdir()
    (home / ".state").mkdir()
    (home / ".state" / "models").mkdir()
    (home / ".scripts").mkdir()
    config_path = home / "config.toml"
    monkeypatch.setattr("nova_ai.core.config.DEFAULT_CONFIG_DIR", home)
    monkeypatch.setattr("nova_ai.core.config.DEFAULT_CONFIG_PATH", config_path)
    # Also patch init_cmd's module-level bindings (imported with ``from ... import``).
    monkeypatch.setattr("nova_ai.cli.init_cmd.DEFAULT_CONFIG_DIR", home)
    monkeypatch.setattr("nova_ai.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path)
    # Patch doctor_cmd's module-level bindings.
    monkeypatch.setattr("nova_ai.cli.doctor_cmd.DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    return home
