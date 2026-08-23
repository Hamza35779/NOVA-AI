"""Tests for VoiceSession."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nova_ai.voice.session import VoiceSession, _clean_text_for_tts


def test_clean_text_for_tts() -> None:
    raw = "Here is the code:\n```python\nprint(1)\n```\nAnd a **bold** item with `variable` and [link](https://example.com)."
    cleaned = _clean_text_for_tts(raw)
    assert "Code block omitted for speech." in cleaned
    assert "bold item with" in cleaned
    assert "link." in cleaned
    assert "https://example.com" not in cleaned
    assert "*" not in cleaned


@patch("nova_ai.voice.session.load_config")
@patch("nova_ai.voice.session.get_speech_backend")
@patch("nova_ai.voice.session.Nova")
def test_voice_session_init(
    mock_nova: MagicMock, mock_get_stt: MagicMock, mock_load_config: MagicMock
) -> None:
    """Test VoiceSession initialization."""
    mock_load_config.return_value = {}
    mock_get_stt.return_value = MagicMock()

    session = VoiceSession(
        model="test-model",
        voice_id="test-voice",
        push_to_talk=True,
        engine_key="test-engine",
    )

    assert session.model == "test-model"
    assert session.voice_id == "test-voice"
    assert session.push_to_talk is True
    assert session.engine_key == "test-engine"
    mock_get_stt.assert_called_once()
    mock_nova.assert_called_once()


@patch("nova_ai.voice.session.check_audio_deps")
@patch("nova_ai.voice.session.load_config")
@patch("nova_ai.voice.session.get_speech_backend")
@patch("nova_ai.voice.session.Nova")
@patch("nova_ai.voice.session.record_until_silence")
def test_exit_keywords_recognized(
    mock_record: MagicMock,
    mock_nova: MagicMock,
    mock_get_stt: MagicMock,
    mock_load_config: MagicMock,
    mock_check_audio: MagicMock,
) -> None:
    """Test that session ends when exit keyword is transcribed."""
    mock_check_audio.return_value = True

    # Mock STT backend
    mock_stt = MagicMock()
    mock_transcription_result = MagicMock()
    mock_transcription_result.text = "quit"
    mock_stt.transcribe.return_value = mock_transcription_result
    mock_get_stt.return_value = mock_stt

    mock_record.return_value = b"fake-audio-data"

    session = VoiceSession()
    session.start()

    # transcribe should have been called once, then broke out of loop
    mock_stt.transcribe.assert_called_once_with(b"fake-audio-data")


@patch("nova_ai.voice.session.check_audio_deps")
@patch("nova_ai.voice.session.load_config")
@patch("nova_ai.voice.session.get_speech_backend")
@patch("nova_ai.voice.session.Nova")
@patch("nova_ai.voice.session.console")
def test_missing_audio_deps_handled(
    mock_console: MagicMock,
    mock_nova: MagicMock,
    mock_get_stt: MagicMock,
    mock_load_config: MagicMock,
    mock_check_audio: MagicMock,
) -> None:
    """Test that session returns immediately if dependencies are missing."""
    mock_check_audio.return_value = False

    session = VoiceSession()
    session.start()

    mock_console.print.assert_called_with(
        "[red]Error: Missing audio dependencies (sounddevice, numpy).[/red]"
    )
