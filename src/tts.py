"""Text to speech. Two voices: a neural online one (more human) and Piper (local, offline).

VOICE=auto uses the online voice when the edge-tts package and the network are available and
falls back to Piper; VOICE=local never leaves the machine. The online voice sends the text of
each answer to Microsoft's speech service.
"""

import asyncio
import io
import os
import wave

from .audio import to_wav
from .paths import PIPER_VOICE

ONLINE_VOICE = os.getenv("ONLINE_VOICE", "es-ES-ElviraNeural")
_state = {"online_failed": False, "piper": None}


def _piper_available() -> bool:
    if not PIPER_VOICE.is_file():
        return False
    try:
        import piper  # noqa: F401
    except ImportError:
        return False
    return True


def _online_available() -> bool:
    if os.getenv("VOICE", "auto").strip().lower() == "local" or _state["online_failed"]:
        return False
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        return False
    return True


def available() -> bool:
    return _online_available() or _piper_available()


def label() -> str:
    if _online_available():
        return f"neuronal en línea ({ONLINE_VOICE})"
    return "Piper local" if _piper_available() else "no instalada"


def _online(text: str) -> bytes:
    import edge_tts

    async def fetch() -> bytes:
        audio = bytearray()
        async for chunk in edge_tts.Communicate(text, ONLINE_VOICE).stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        return bytes(audio)

    return to_wav(asyncio.run(asyncio.wait_for(fetch(), timeout=30)), rate=24000)


def _piper(text: str) -> bytes:
    if _state["piper"] is None:
        from piper import PiperVoice
        _state["piper"] = PiperVoice.load(str(PIPER_VOICE))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        _state["piper"].synthesize_wav(text, wav_file)
    return buffer.getvalue()


def synthesize(text: str) -> bytes | None:
    """Return WAV bytes, or None when no voice is installed."""
    if not text.strip():
        return None
    if _online_available():
        try:
            return _online(text)
        except Exception:  # no network or service change: use the local voice from now on
            _state["online_failed"] = True
    try:
        return _piper(text) if _piper_available() else None
    except Exception:  # a broken voice must not take the text, the table or the PDF with it
        return None
