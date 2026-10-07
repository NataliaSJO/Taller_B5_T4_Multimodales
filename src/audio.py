"""Optional local Whisper transcription; no audio is uploaded to a server."""

import tempfile
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel
    return WhisperModel("base", device="cpu", compute_type="int8")


def transcribe_audio(payload: bytes, suffix: str = ".wav") -> str:
    if not payload or len(payload) > 25 * 1024 * 1024:
        raise ValueError("El audio debe ocupar entre 1 byte y 25 MiB")
    if suffix.lower() not in (".wav", ".mp3", ".m4a"):
        raise ValueError("Formato de audio no admitido")
    try:
        model = _model()
    except ImportError as exc:
        raise RuntimeError("Instala requirements-voice.txt para activar la transcripción") from exc
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(payload)
        filename = handle.name
    try:
        segments, _ = model.transcribe(filename, language="es", vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()
    finally:
        Path(filename).unlink(missing_ok=True)
