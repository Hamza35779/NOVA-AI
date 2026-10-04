"""Tests for GGUF model discovery and Hugging Face downloads.

The in-process GGUF engine must work without Ollama: any Hugging
Face-downloaded ``.gguf`` dropped into ``~/.nova_ai/models`` has to be
discoverable, and ``download_gguf_model`` must accept custom
``repo::file`` pairs from anywhere on the Hub.
"""

from __future__ import annotations

from unittest import mock

import pytest

from nova_ai.engine import gguf


@pytest.fixture()
def models_dir(tmp_path, monkeypatch):
    """Redirect the GGUF models dir into a tmp_path."""
    monkeypatch.setenv("NOVA_MODELS_DIR", str(tmp_path))
    return tmp_path


class TestListInstalledGgufModels:
    def test_empty_dir_lists_nothing(self, models_dir) -> None:
        assert gguf.list_installed_gguf_models() == []

    def test_catalog_model_listed_by_id(self, models_dir) -> None:
        entry = gguf.GGUF_CATALOG[0]
        (models_dir / entry["filename"]).touch()
        assert gguf.list_installed_gguf_models() == [entry["id"]]

    def test_loose_hf_download_discovered_by_filename(self, models_dir) -> None:
        """A HF-downloaded .gguf with no catalog entry still shows up."""
        (models_dir / "MyFineTune-Q4_K_M.gguf").touch()
        assert gguf.list_installed_gguf_models() == ["MyFineTune-Q4_K_M.gguf"]

    def test_loose_file_matching_catalog_name_not_duplicated(
        self, models_dir
    ) -> None:
        entry = gguf.GGUF_CATALOG[0]
        (models_dir / entry["filename"]).touch()
        listed = gguf.list_installed_gguf_models()
        assert listed == [entry["id"]]

    def test_non_gguf_files_ignored(self, models_dir) -> None:
        (models_dir / "readme.txt").touch()
        (models_dir / "model.safetensors").touch()
        assert gguf.list_installed_gguf_models() == []


class TestDownloadGgufModel:
    def test_unknown_id_still_raises(self, models_dir) -> None:
        with pytest.raises(ValueError, match="Unknown model ID"):
            gguf.download_gguf_model("not-a-real-model")

    def test_custom_repo_pair_builds_hf_url(self, models_dir) -> None:
        """repo::file downloads from the Hub into the shared models dir."""
        captured: dict = {}

        class _FakeDownloader:
            def __init__(self, *a, **kw):
                pass

            def download(self, spec):
                captured["url"] = spec.url
                captured["dest"] = spec.dest
                spec.dest.touch()

        with mock.patch(
            "nova_ai.engine.model_downloader.ResilientDownloader",
            _FakeDownloader,
        ):
            path = gguf.download_gguf_model("someone/cool-GGUF::My-Q4_K_M.gguf")

        assert path == models_dir / "My-Q4_K_M.gguf"
        assert path.exists()
        assert captured["url"] == (
            "https://huggingface.co/someone/cool-GGUF/resolve/main/My-Q4_K_M.gguf"
        )

    def test_custom_pair_skips_existing_download(self, models_dir) -> None:
        dest = models_dir / "My-Q4_K_M.gguf"
        dest.write_bytes(b"already here")
        path = gguf.download_gguf_model("someone/cool-GGUF::My-Q4_K_M.gguf")
        assert path == dest

    def test_malformed_pair_raises(self, models_dir) -> None:
        with pytest.raises(ValueError, match="owner/repo"):
            gguf.download_gguf_model("::file-only.gguf")

    def test_catalog_id_unchanged(self, models_dir) -> None:
        """Catalog ids keep resolving to their pinned repo/file."""
        entry = gguf.GGUF_CATALOG[0]

        class _FakeDownloader:
            def __init__(self, *a, **kw):
                pass

            def download(self, spec):
                spec.dest.touch()

        with mock.patch(
            "nova_ai.engine.model_downloader.ResilientDownloader",
            _FakeDownloader,
        ):
            path = gguf.download_gguf_model(entry["id"])

        assert path == models_dir / entry["filename"]
