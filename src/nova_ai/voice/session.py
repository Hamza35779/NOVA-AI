"""Core VoiceSession class with speech cleanup and low-latency audio interaction."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

from rich.console import Console
from rich.panel import Panel

from nova_ai.core.config import load_config
from nova_ai.sdk import Nova
from nova_ai.speech._discovery import get_speech_backend
from nova_ai.speech._stubs import SpeechBackend, TranscriptionResult
from nova_ai.speech.tts import TTSBackend, TTSResult
from nova_ai.voice.audio_io import (
    check_audio_deps,
    listen_for_wake_word,
    play_audio,
    record_until_silence,
)

console = Console()

# Matched as whole words/phrases against lowercased, punctuation-stripped input.
EXIT_KEYWORDS = frozenset(
    {
        "exit",
        "quit",
        "goodbye",
        "good bye",
        "stop",
        "bye",
        "bye bye",
        "see you",
        "see ya",
        "farewell",
        "good night",
        "end session",
        "shut down",
        "shutdown",
        "that's all",
        "thats all",
    }
)

_RE_CODE_BLOCK = re.compile(r"```[\s\S]*?```")
_RE_INLINE_CODE = re.compile(r"`[^`]*`")
_RE_MD_LINK = re.compile(r"\[([^\]]+)\]\([^\)]+\)")
# Strip blockquote markers only at line starts; inline ">" (e.g. "I > you") is preserved.
_RE_BLOCKQUOTE = re.compile(r"(?m)^\s{0,3}>+\s?")
_RE_MD_EMPHASIS = re.compile(r"[*_#~]")
_RE_WHITESPACE = re.compile(r"\s+")


def _clean_text_for_tts(text: str) -> str:
    """Strip markdown code blocks, backticks, asterisks, and links for natural TTS speech.

    Comparison operators like ">" are preserved in inline contexts so sentences
    such as "x > y" are spoken correctly; only markdown blockquote markers at
    the start of a line are removed.
    """
    cleaned = _RE_CODE_BLOCK.sub(" Code block omitted for speech. ", text)
    cleaned = _RE_INLINE_CODE.sub(" ", cleaned)
    cleaned = _RE_MD_LINK.sub(r"\1", cleaned)
    cleaned = _RE_BLOCKQUOTE.sub("", cleaned)
    cleaned = _RE_MD_EMPHASIS.sub("", cleaned)
    cleaned = _RE_WHITESPACE.sub(" ", cleaned).strip()
    return cleaned


class VoiceSession:
    """Interactive voice chat session managing the listen-think-speak cycle."""

    def __init__(
        self,
        config: Optional[Any] = None,
        model: Optional[str] = None,
        voice_id: str = "af_heart",
        push_to_talk: bool = False,
        engine_key: Optional[str] = None,
        max_turns: int = 0,
        silence_threshold: int = 500,
        history_turns: int = 5,
        wake_word: Optional[str] = None,
        wake_word_timeout: float = 30.0,
    ) -> None:
        """
        Args:
            max_turns: Stop after this many exchanges (0 = unlimited).
            silence_threshold: RMS level below which mic input counts as silence.
            history_turns: How many prior exchanges to carry into each prompt.
        """
        self.config = config or load_config()
        self.model = model
        self.voice_id = voice_id
        self.push_to_talk = push_to_talk
        self.engine_key = engine_key
        self.max_turns = max(0, int(max_turns))
        self.silence_threshold = silence_threshold
        self.history_turns = max(0, int(history_turns))
        self.history: List[Tuple[str, str]] = []
        self.wake_word = wake_word
        self.wake_word_timeout = wake_word_timeout

        self.nova = Nova(config=self.config, engine_key=self.engine_key)
        self.stt_backend = self._get_stt_backend()
        self.tts_backend = self._get_tts_backend()

    def _get_stt_backend(self) -> SpeechBackend:
        return get_speech_backend(self.config)

    def _get_tts_backend(self) -> Optional[TTSBackend]:
        try:
            from nova_ai.speech.tts import TTSRegistry

            keys = sorted(TTSRegistry.keys())
            if not keys:
                return None
            # Prefer kokoro when available; otherwise fall back deterministically.
            preferred = "kokoro" if "kokoro" in keys else keys[0]
            return TTSRegistry.get(preferred)
        except (ImportError, AttributeError):
            pass
        return None

    @staticmethod
    def _is_exit_command(text: str) -> bool:
        """Normalize and match transcript against the exit keyword set."""
        normalized = re.sub(r"[^\w\s']", " ", text.lower()).strip()
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized in EXIT_KEYWORDS

    def _build_contextual_prompt(self, text: str) -> str:
        """Prepend recent conversation turns so multi-turn voice chats keep context."""
        if not self.history or self.history_turns <= 0:
            return text
        recent = self.history[-self.history_turns :]
        context_block = "\n".join(f"User: {u}\nNova: {r}" for u, r in recent)
        return f"[Conversation so far]\n{context_block}\n\nUser: {text}"

    def start(self) -> None:
        """Main conversation loop."""
        if not check_audio_deps():
            console.print(
                "[red]Error: Missing audio dependencies (sounddevice, numpy).[/red]"
            )
            return

        console.print(
            Panel.fit(
                "[bold green]NOVA AI[/bold green] Voice Mode Active",
                border_style="purple",
            )
        )
        stt_name = self.stt_backend.__class__.__name__ if self.stt_backend else "None"
        tts_name = self.tts_backend.__class__.__name__ if self.tts_backend else "None"
        console.print(
            f"STT Backend: [cyan]{stt_name}[/cyan] | TTS Backend: [cyan]{tts_name}[/cyan]"
        )
        console.print(
            "Say [bold yellow]'exit'[/bold yellow], [bold yellow]'quit'[/bold yellow], or [bold yellow]'goodbye'[/bold yellow] to stop.\n"
        )

        turns_completed = 0
        while True:
            if self.max_turns and turns_completed >= self.max_turns:
                console.print(
                    f"[yellow]Reached maximum of {self.max_turns} turns. Ending session.[/yellow]"
                )
                break
            try:
                if self.wake_word:
                    console.print(f"[dim]Listening for wake-word: [bold]{self.wake_word}[/bold]...[/dim]")
                    detected = listen_for_wake_word(
                        keyword=self.wake_word,
                        timeout_seconds=self.wake_word_timeout,
                    )
                    if not detected:
                        continue
                    console.print("[bold green]Wake-word detected! Listening...[/bold green]")
                elif self.push_to_talk:
                    console.print("[dim]Press [bold]Enter[/bold] to speak (Ctrl+C to exit)...[/dim]")
                    try:
                        input()
                    except EOFError:
                        break

                audio_data = record_until_silence(
                    silence_threshold=self.silence_threshold
                )
                if not audio_data:
                    continue

                console.print("\n[dim]Transcribing...[/dim]")
                try:
                    result: TranscriptionResult = self.stt_backend.transcribe(
                        audio_data
                    )
                    text = (result.text or "").strip()
                except Exception as e:
                    console.print(f"[red]STT Error: {e}[/red]")
                    continue

                if not text:
                    continue

                console.print(f"[bold cyan]You:[/bold cyan] {text}")

                if self._is_exit_command(text):
                    console.print("[bold green]Goodbye![/bold green]")
                    break

                console.print("[dim]Thinking...[/dim]")
                response = self.nova.ask(
                    self._build_contextual_prompt(text), model=self.model
                )

                self.history.append((text, response))
                turns_completed += 1

                console.print(f"[bold magenta]Nova:[/bold magenta] {response}")

                if self.tts_backend:
                    try:
                        tts_speech = _clean_text_for_tts(response)
                        tts_result: TTSResult = self.tts_backend.synthesize(
                            tts_speech, voice_id=self.voice_id
                        )
                        audio_payload = getattr(
                            tts_result,
                            "audio",
                            getattr(tts_result, "audio_bytes", None),
                        )
                        if audio_payload:
                            play_audio(
                                audio_payload, sample_rate=tts_result.sample_rate
                            )
                    except Exception as e:
                        console.print(
                            f"[yellow]TTS Warning (Audio skipped): {e}[/yellow]"
                        )

            except KeyboardInterrupt:
                console.print("\n[bold green]Exiting Voice Session...[/bold green]")
                break
            except Exception as e:
                console.print(f"[red]Error in voice loop: {e}[/red]")


__all__ = ["VoiceSession", "_clean_text_for_tts", "EXIT_KEYWORDS"]
