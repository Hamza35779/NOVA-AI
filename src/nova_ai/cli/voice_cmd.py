"""Voice command CLI."""

from __future__ import annotations

import click

from nova_ai.voice.audio_io import check_audio_deps
from nova_ai.voice.session import VoiceSession


@click.command()
@click.option("--model", default=None, help="LLM model to use")
@click.option("--voice", default="af_heart", help="TTS voice ID")
@click.option(
    "--push-to-talk",
    is_flag=True,
    default=False,
    help="Require Enter to start recording",
)
@click.option("--engine", "engine_key", default=None, help="Engine backend")
def voice(model: str, voice: str, push_to_talk: bool, engine_key: str) -> None:
    """Start a voice conversation with Nova."""
    if not check_audio_deps():
        click.secho(
            "Missing audio dependencies.\n"
            "Please install sounddevice and numpy:\n"
            "  pip install sounddevice numpy",
            fg="red",
        )
        return

    session = VoiceSession(
        model=model, voice_id=voice, push_to_talk=push_to_talk, engine_key=engine_key
    )
    session.start()
