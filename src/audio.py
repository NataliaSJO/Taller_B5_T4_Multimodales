"""Local Whisper transcription; no audio is uploaded to a server."""

import io
import re
import tempfile
import unicodedata
from functools import lru_cache
from pathlib import Path

from .paths import WHISPER_DIR, WHISPER_SIZE

# Formats the page accepts; recordings from the browser arrive as WAV.
AUDIO_TYPES = ["wav", "mp3", "m4a", "ogg", "opus", "flac", "aac", "webm", "mp4"]


# Given silence or noise, Whisper writes credits it saw in subtitled videos. They are never
# something a client says to an adviser, so a transcript that is only this counts as no speech.
PHANTOMS = re.compile(
    r"subtitulos? (?:por|realizados por|de) (?:la )?comunidad de amara\.?org|amara\.?org|"
    r"subtitulos? (?:por|realizados por|creados por)\b.*|gracias por ver(?: el video)?|"
    r"suscribete(?: al canal)?|no olvides suscribirte.*|musica|aplausos|\[.*?\]|\(.*?\)")


def spoken(segments) -> str:
    """Join what was really said: drop segments Whisper itself doubts and its stock phantom lines."""
    kept = []
    for segment in segments:
        text = segment.text.strip()
        plain = "".join(char for char in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(char))
        plain = PHANTOMS.sub(" ", plain)
        if not re.search(r"[a-z0-9]", plain):
            continue                      # nothing left but a phantom line
        if segment.no_speech_prob > 0.6 and segment.avg_logprob < -1.0:
            continue                      # the model thinks this stretch is not speech
        kept.append(text)
    return " ".join(kept).strip()


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel
    source = str(WHISPER_DIR) if (WHISPER_DIR / "model.bin").is_file() else WHISPER_SIZE
    return WhisperModel(source, device="cpu", compute_type="int8")


def warm():
    """Load Whisper ahead of the first recording."""
    _model()


def to_wav(payload: bytes, rate: int = 16000) -> bytes:
    """Any audio (webm from the browser, mp3, m4a...) -> mono 16-bit WAV."""
    import av

    out = io.BytesIO()
    with av.open(io.BytesIO(payload)) as source, av.open(out, "w", format="wav") as target:
        stream = target.add_stream("pcm_s16le", rate=rate, layout="mono")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
        for frame in source.decode(audio=0):
            for resampled in resampler.resample(frame):
                target.mux(stream.encode(resampled))
        target.mux(stream.encode(None))
    return out.getvalue()


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
            segments, _ = model.transcribe(filename, language="es", vad_filter=vad,
                                           condition_on_previous_text=False)
            text = spoken(segments)
            if text:
                return text
        return ""
    finally:
        Path(filename).unlink(missing_ok=True)
