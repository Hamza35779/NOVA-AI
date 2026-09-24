"""Tests for ``nova config reset``."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from nova_ai.cli.config_cmd import reset


class TestConfigReset:
    def test_reset_requires_confirmation(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text('[server]\nhost = "127.0.0.1"\n', encoding="utf-8")
        result = CliRunner().invoke(reset, ["--path", str(cfg)], input="n\n")
        assert result.exit_code == 0
        assert cfg.exists(), "aborting must leave the config untouched"

    def test_reset_with_yes_backs_up_and_removes(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text('[server]\nhost = "127.0.0.1"\n', encoding="utf-8")
        result = CliRunner().invoke(reset, ["--yes", "--path", str(cfg)])
        assert result.exit_code == 0
        assert not cfg.exists()
        backups = list(tmp_path.glob("config.toml.bak-*"))
        assert len(backups) == 1
        assert 'host = "127.0.0.1"' in backups[0].read_text(encoding="utf-8")

    def test_reset_missing_config_is_noop(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(reset, ["--yes", "--path", str(tmp_path / "nope.toml")])
        assert result.exit_code == 0
        assert "nothing to reset" in result.output

    def test_reset_prompt_default_is_no(self, tmp_path: Path) -> None:
        """Plain Enter at the prompt must abort (destructive-by-confirmation)."""
        cfg = tmp_path / "config.toml"
        cfg.write_text("x = 1\n", encoding="utf-8")
        result = CliRunner().invoke(reset, ["--path", str(cfg)], input="\n")
        assert result.exit_code == 0
        assert cfg.exists()
