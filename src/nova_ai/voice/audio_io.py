"""Low-level audio I/O helpers."""

from __future__ import annotations

import io
import time
import wave
from typing import Optional

try:
    import numpy as np
    import sounddevice as sd

    HAS_AUDIO_DEPS = True
except ImportError:
    HAS_AUDIO_DEPS = False


def check_audio_deps() -> bool:
    """Check if sounddevice and numpy are available."""
    return HAS_AUDIO_DEPS


def record_until_silence(
    sample_rate: int = 16000,
    silence_threshold: int = 500,
    silence_duration: float = 1.5,
    max_duration: int = 30,
) -> bytes:
    """Record audio from microphone until silence is detected.

    Args:
        sample_rate: Audio sampling rate in Hz.
        silence_threshold: RMS threshold below which audio is considered silent.
        silence_duration: Seconds of continuous silence before stopping.
        max_duration: Maximum recording time in seconds.

    Returns:
        WAV-encoded bytes.
    """
    if not HAS_AUDIO_DEPS:
        raise RuntimeError("sounddevice and numpy are required for audio I/O.")

    frames: list[np.ndarray] = []

    import queue

    q = queue.Queue()

    def callback(
        indata: np.ndarray, frames_count: int, time_info: dict, status: sd.CallbackFlags
    ) -> None:
        if status:
            pass
        q.put(indata.copy())

    print("Listening...", end="", flush=True)

    start_time = time.time()
    silence_start: Optional[float] = None

    with sd.InputStream(
        samplerate=sample_rate, channels=1, dtype="int16", callback=callback
    ):
        while True:
            if time.time() - start_time > max_duration:
                break

            try:
                data = q.get(timeout=0.1)
                frames.append(data)

                rms = np.sqrt(np.mean(data.astype(np.float32) ** 2))

                if rms < silence_threshold:
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start > silence_duration:
                        break
                else:
                    silence_start = None

            except queue.Empty:
                continue

    print("\rProcessing...", end="\r", flush=True)

    if not frames:
        return b""

    audio_data = np.concatenate(frames, axis=0)

    wav_io = io.BytesIO()
    with wave.open(wav_io, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data.tobytes())

    return wav_io.getvalue()


def play_audio(audio_bytes: bytes, sample_rate: int = 24000) -> None:
    """Play audio bytes through speakers.

    Args:
        audio_bytes: Raw PCM audio bytes.
        sample_rate: Sample rate for playback.
    """
    if not HAS_AUDIO_DEPS:
        raise RuntimeError("sounddevice and numpy are required for audio I/O.")

    if not audio_bytes:
        return

    audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
    sd.play(audio_array, samplerate=sample_rate)
    sd.wait()
