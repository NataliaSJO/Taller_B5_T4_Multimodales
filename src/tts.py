"""Local text-to-speech with a Piper voice; nothing is sent to a server."""

import io
import wave
from functools import lru_cache

from .paths import PIPER_VOICE


@lru_cache(maxsize=1)
def _voice():
    from piper import PiperVoice
    return PiperVoice.load(str(PIPER_VOICE))


def available() -> bool:
    if not PIPER_VOICE.is_file():
        return False
    try:
        import piper  # noqa: F401
    except ImportError:
        return False
    return True


def synthesize(text: str) -> bytes | None:
    """Return WAV bytes, or None when the voice is not installed."""
    if not text.strip() or not available():
        return None
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        _voice().synthesize_wav(text, wav_file)
    return buffer.getvalue()
