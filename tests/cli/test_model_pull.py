"""Tests for ``nova model pull`` multi-engine support."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from click.testing import CliRunner
from rich.console import Console

from nova_ai.cli.model import ollama_pull


class TestOllamaPull:
    """Test the extracted ollama_pull helper."""

    def test_ollama_pull_success(self) -> None:
        import io

        console = Console(file=io.StringIO())
        mock_lines = [
            '{"status": "pulling manifest"}',
            '{"status": "downloading", "total": 100, "completed": 100}',
            '{"status": "success"}',
        ]
        mock_resp = mock.MagicMock()
        mock_resp.raise_for_status = mock.MagicMock()
        mock_resp.iter_lines.return_value = iter(mock_lines)
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("httpx.stream", return_value=mock_resp):
            result = ollama_pull("http://localhost:11434", "qwen3.5:2b", console)
        assert result is True

    def test_ollama_pull_connect_error(self) -> None:
        import io

        import httpx

        console = Console(file=io.StringIO())
        with mock.patch("httpx.stream", side_effect=httpx.ConnectError("refused")):
            result = ollama_pull("http://localhost:11434", "qwen3.5:2b", console)
        assert result is False


class TestPullCliMultiEngine:
    """Test the pull CLI command dispatches to correct engine."""

    def test_pull_llamacpp_downloads_gguf_to_models_dir(self) -> None:
        """llamacpp pulls land in ~/.nova_ai/models (resilient downloader).

        The old huggingface-cli route dropped the file into the HF cache,
        which no NOVA engine reads, leaving the pull unusable.
        """
        from nova_ai.cli import cli

        runner = CliRunner()
        with (
            mock.patch("nova_ai.cli.model.load_config") as mock_cfg,
            mock.patch("nova_ai.cli.model._gguf_runtime_ready", return_value=True),
            mock.patch("nova_ai.cli.model.download_gguf_model") as mock_dl,
        ):
            mock_cfg.return_value.engine.default = "llamacpp"
            mock_cfg.return_value.engine.ollama_host = None
            mock_dl.return_value = Path("Qwen3.5-9B-Q4_K_M.gguf")

            result = runner.invoke(
                cli, ["model", "pull", "qwen3.5:9b", "--engine", "llamacpp"]
            )

        assert result.exit_code == 0
        mock_dl.assert_called_once()
        # Qwen ships no GGUF for Qwen3.5; the catalog points at the
        # unsloth mirror (file verified 200 on HF, 2026-09-23).
        assert mock_dl.call_args[0][0] == (
            "unsloth/Qwen3.5-9B-GGUF::Qwen3.5-9B-Q4_K_M.gguf"
        )
        assert "Qwen3.5-9B-Q4_K_M.gguf" in result.output

    def test_pull_mlx_uses_huggingface_cli(self) -> None:
        from nova_ai.cli import cli

        runner = CliRunner()
        with (
            mock.patch("nova_ai.cli.model.load_config") as mock_cfg,
            mock.patch("subprocess.run") as mock_run,
        ):
            mock_cfg.return_value.engine.default = "mlx"
            mock_cfg.return_value.engine.ollama_host = None
            mock_run.return_value = mock.MagicMock(returncode=0)

            result = runner.invoke(
                cli, ["model", "pull", "qwen3.5:9b", "--engine", "mlx"]
            )

        assert result.exit_code == 0
        mock_run.assert_called_once()


class TestGgufPull:
    """``--engine gguf`` pulls must work with zero external services."""

    def test_pull_gguf_catalog_id(self) -> None:
        from nova_ai.cli import cli

        runner = CliRunner()
        with (
            mock.patch("nova_ai.cli.model.load_config") as mock_cfg,
            mock.patch("nova_ai.cli.model._gguf_runtime_ready", return_value=True),
            mock.patch("nova_ai.cli.model.download_gguf_model") as mock_dl,
        ):
            mock_cfg.return_value.engine.default = "gguf"
            mock_cfg.return_value.engine.ollama_host = None
            mock_dl.return_value = Path("qwen2.5-0.5b-instruct-q4_k_m.gguf")

            result = runner.invoke(
                cli, ["model", "pull", "qwen2.5-0.5b", "--engine", "gguf"]
            )

        assert result.exit_code == 0
        assert mock_dl.call_args[0][0] == (
            "Qwen/Qwen2.5-0.5B-Instruct-GGUF::qwen2.5-0.5b-instruct-q4_k_m.gguf"
        )
        assert "--engine gguf" in result.output  # usage hint names the engine

    def test_pull_gguf_custom_hf_pair(self) -> None:
        """Any owner/repo::file.gguf from the Hub is pullable."""
        from nova_ai.cli import cli

        runner = CliRunner()
        with (
            mock.patch("nova_ai.cli.model.load_config") as mock_cfg,
            mock.patch("nova_ai.cli.model._gguf_runtime_ready", return_value=True),
            mock.patch("nova_ai.cli.model.download_gguf_model") as mock_dl,
        ):
            mock_cfg.return_value.engine.default = "gguf"
            mock_cfg.return_value.engine.ollama_host = None
            mock_dl.return_value = Path("MyModel-Q4_K_M.gguf")

            result = runner.invoke(
                cli,
                [
                    "model",
                    "pull",
                    "someone/cool-model-GGUF::MyModel-Q4_K_M.gguf",
                    "--engine",
                    "gguf",
                ],
            )

        assert result.exit_code == 0
        assert mock_dl.call_args[0][0] == (
            "someone/cool-model-GGUF::MyModel-Q4_K_M.gguf"
        )

    def test_pull_gguf_runtime_missing_shows_install_hint(self) -> None:
        """No llama-cpp-python -> fail BEFORE the multi-GB download."""
        from nova_ai.cli import cli

        runner = CliRunner()
        with (
            mock.patch("nova_ai.cli.model.load_config") as mock_cfg,
            mock.patch.dict("sys.modules", {"llama_cpp": None}),
        ):
            mock_cfg.return_value.engine.default = "gguf"
            mock_cfg.return_value.engine.ollama_host = None

            result = runner.invoke(
                cli, ["model", "pull", "qwen2.5-0.5b", "--engine", "gguf"]
            )

        assert result.exit_code == 1
        assert "llama-cpp-python" in result.output
        assert "Downloading" not in result.output
