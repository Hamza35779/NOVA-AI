"""Tests for Faster-Whisper speech backend."""

from subprocess import PIPE, check_output
from sys import executable
from unittest.mock import MagicMock

import pytest

import nova_ai.speech.faster_whisper as fw
from nova_ai.core.registry import SpeechRegistry
from nova_ai.speech.faster_whisper import FasterWhisperBackend


@pytest.fixture(autouse=True)
def _register_faster_whisper():
    """Re-register after any registry clear."""
    if not SpeechRegistry.contains("faster-whisper"):
        SpeechRegistry.register_value("faster-whisper", FasterWhisperBackend)


def _inject_deps(monkeypatch, whisper_cls, ct2=None):
    """Skip the lazy loader as if it already ran, with the given fakes."""
    monkeypatch.setattr(fw, "_deps_attempted", True)
    monkeypatch.setattr(fw, "_whisper_cls", whisper_cls)
    monkeypatch.setattr(fw, "_ct2", ct2)


def test_faster_whisper_backend_registers():
    """Backend registers itself in SpeechRegistry."""
    assert SpeechRegistry.contains("faster-whisper")


def test_faster_whisper_module_import_stays_light():
    """Importing the backend module must not pull heavy libs (#404/#309).

    The speech package imports every backend while registering it, so an
    eager `import faster_whisper` here would drag numpy into every `nova`
    command. The loader must stay deferred until first use.
    """
    out = check_output(
        [
            executable,
            "-c",
            "import sys; import nova_ai.speech.faster_whisper; "
            "leaked = [m for m in sys.modules if m == 'numpy' or m.startswith('numpy.') or m == 'faster_whisper']; "
            "print(';'.join(leaked))",
        ],
        stderr=PIPE,
    )
    leaked = out.decode().strip()
    assert leaked == "", f"eager imports leaked into module load: {leaked}"


def test_faster_whisper_transcribe(monkeypatch):
    """Transcribe returns a TranscriptionResult."""
    from nova_ai.speech._stubs import TranscriptionResult

    mock_model = MagicMock()
    mock_segment = MagicMock()
    mock_segment.text = " Hello world"
    mock_segment.start = 0.0
    mock_segment.end = 1.2
    mock_segment.avg_logprob = -0.3

    mock_info = MagicMock()
    mock_info.language = "en"
    mock_info.language_probability = 0.95
    mock_info.duration = 1.5

    mock_model.transcribe.return_value = ([mock_segment], mock_info)

    _inject_deps(monkeypatch, MagicMock(return_value=mock_model))

    backend = FasterWhisperBackend(model_size="base", device="cpu")
    result = backend.transcribe(b"fake audio bytes")

    assert isinstance(result, TranscriptionResult)
    assert result.text == "Hello world"
    assert result.language == "en"
    assert result.duration_seconds == 1.5


def test_faster_whisper_falls_back_from_unsupported_float16(monkeypatch):
    mock_model = MagicMock()

    _inject_deps(
        monkeypatch,
        MagicMock(return_value=mock_model),
        ct2=MagicMock(
            get_supported_compute_types=MagicMock(return_value={"float32", "int8"})
        ),
    )
    whisper_cls = fw._whisper_cls

    backend = FasterWhisperBackend(
        model_size="base",
        device="cpu",
        compute_type="float16",
    )
    assert backend._ensure_model() is mock_model

    whisper_cls.assert_called_once_with("base", device="cpu", compute_type="int8")


def test_faster_whisper_missing_dependency_hint_uses_desktop_extra(monkeypatch):
    _inject_deps(monkeypatch, None)
    backend = FasterWhisperBackend()

    with pytest.raises(ImportError) as excinfo:
        backend._ensure_model()

    assert "uv sync --extra desktop" in str(excinfo.value)
    assert "uv sync --extra speech" not in str(excinfo.value)


def test_faster_whisper_health_no_model(monkeypatch):
    """Health returns False before model is loaded."""
    _inject_deps(monkeypatch, None)
    backend = FasterWhisperBackend()
    assert backend.health() is False
    assert "uv sync --extra desktop" in (backend.last_error() or "")


def test_faster_whisper_health_captures_load_error(monkeypatch):
    _inject_deps(
        monkeypatch,
        MagicMock(side_effect=RuntimeError("missing cublas64_12.dll")),
    )
    backend = FasterWhisperBackend()
    assert backend.health() is False
    assert "missing cublas64_12.dll" in (backend.last_error() or "")


def test_faster_whisper_supported_formats():
    """Backend supports standard audio formats."""
    backend = FasterWhisperBackend.__new__(FasterWhisperBackend)
    formats = backend.supported_formats()
    assert "wav" in formats
    assert "mp3" in formats
    assert "webm" in formats
