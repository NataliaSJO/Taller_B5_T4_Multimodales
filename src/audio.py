"""Local Whisper transcription; no audio is uploaded to a server."""

import tempfile
from functools import lru_cache
from pathlib import Path

from .paths import WHISPER_DIR, WHISPER_SIZE

# Formats the page accepts; recordings from the browser arrive as WAV.
AUDIO_TYPES = ["wav", "mp3", "m4a", "ogg", "opus", "flac", "aac", "webm", "mp4"]


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel
    source = str(WHISPER_DIR) if (WHISPER_DIR / "model.bin").is_file() else WHISPER_SIZE
    return WhisperModel(source, device="cpu", compute_type="int8")


def transcribe_audio(payload: bytes, suffix: str = ".wav") -> str:
    if not payload or len(payload) > 25 * 1024 * 1024:
        raise ValueError("El audio debe ocupar entre 1 byte y 25 MiB")
    if suffix.lower().lstrip(".") not in AUDIO_TYPES:
        raise ValueError("Formato de audio no admitido")
    try:
        model = _model()
    except ImportError as exc:
        raise RuntimeError("Instala requirements.txt para activar la transcripción") from exc
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(payload)
        filename = handle.name
    try:
        for vad in (True, False):  # the voice filter can drop one-word answers such as «cinco»
            segments, _ = model.transcribe(filename, language="es", vad_filter=vad)
            text = " ".join(segment.text.strip() for segment in segments).strip()
            if text:
                return text
        return ""
    finally:
        Path(filename).unlink(missing_ok=True)
