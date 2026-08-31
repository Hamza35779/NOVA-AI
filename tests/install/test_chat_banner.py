"""Tests for the chat startup banner."""

from __future__ import annotations

from pathlib import Path

from nova_ai.cli import _bg_state
from nova_ai.cli._chat_banner import render_startup_banner


def test_banner_empty_when_all_ready(tmp_nova_ai_home: Path) -> None:
    (tmp_nova_ai_home / ".state" / "extension-built").write_text("")
    # Model ids contain ':', which NTFS treats as an ADS separator —
    # write the sanitized form that pull-model.sh produces on Windows.
    (tmp_nova_ai_home / ".state" / "models" / "qwen3.5_9b.ready").write_text("")
    s = _bg_state.get_status()
    banner = render_startup_banner(s)
    assert banner == ""


def test_banner_shows_rust_building(tmp_nova_ai_home: Path) -> None:
    """Pending rust ext (no marker file) is shown as 'building'."""
    s = _bg_state.get_status()  # all pending
    banner = render_startup_banner(s)
    assert "Rust extension" in banner
    assert "building" in banner.lower()


def test_banner_shows_model_downloading(tmp_nova_ai_home: Path) -> None:
    (tmp_nova_ai_home / ".state" / "extension-built").write_text("")
    models_dir = tmp_nova_ai_home / ".state" / "models"
    # Sanitized filename (':' → '_'); get_status restores the colon.
    (models_dir / "qwen3.5_9b.downloading").write_text("")
    s = _bg_state.get_status()
    banner = render_startup_banner(s)
    assert "qwen3.5:9b" in banner
    assert "downloading" in banner.lower()


def test_banner_shows_failed_in_dim_warning(tmp_nova_ai_home: Path) -> None:
    (tmp_nova_ai_home / ".state" / "extension-failed").write_text("error tail")
    s = _bg_state.get_status()
    banner = render_startup_banner(s)
    assert "failed" in banner.lower()
    assert "doctor" in banner.lower()
