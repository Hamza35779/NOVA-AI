"""Tests for speech configuration."""

from nova_ai.core.config import NovaConfig, SpeechConfig


def test_speech_config_defaults():
    cfg = SpeechConfig()
    assert cfg.backend == "auto"
    assert cfg.model == "base"
    assert cfg.language == ""
    assert cfg.device == "auto"
    assert cfg.compute_type == "float16"


def test_nova_config_has_speech():
    cfg = NovaConfig()
    assert hasattr(cfg, "speech")
    assert isinstance(cfg.speech, SpeechConfig)
    assert cfg.speech.backend == "auto"


def test_nova_system_has_speech_backend():
    """NovaSystem has a speech_backend attribute."""
    from nova_ai.system import NovaSystem

    assert "speech_backend" in NovaSystem.__dataclass_fields__
