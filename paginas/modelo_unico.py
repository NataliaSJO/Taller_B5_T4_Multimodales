"""Versión alternativa: un único modelo multimodal (Gemma 3n) oye, entiende, pregunta y elige."""

import tempfile
import time
from pathlib import Path

import streamlit as st

from src import omni, tts, ui
from src.audio import to_wav
from src.conversation import GREETING, extra_question, is_yes, merge, missing, question, relax

AUDIO = (".wav", ".mp3", ".flac", ".ogg")
IMAGES = (".png", ".jpg", ".jpeg")


def handle(text: str, audio: list[str], images: list[str], funds, source: str):
    state = st.session_state
    history = [(message["role"], message["text"]) for message in state.messages]
    try:
        new, transcript, ask = omni.understand(history, state.profile, text, audio, images)
    except ValueError:  # the model did not return usable JSON
        state.messages.append({"role": "user", "text": text or "(mensaje de voz)"})
        ui.say("No te he entendido bien. ¿Puedes repetirlo con otras palabras?")
        return
    state.messages.append({"role": "user", "text": transcript or text or "(mensaje de voz)"})
    pending_relax = state.pop("relax", None)
    if pending_relax and is_yes(transcript):
        state.profile = relax(state.profile, pending_relax)
    else:
        state.profile = merge(state.profile, new)
    state.pending = missing(state.profile)
    if state.pending:
        ui.say(ask or question(state.profile))
    elif not state.get("extra_asked") and extra_question(state.profile):
        state.extra_asked = True
        ui.say(ask or extra_question(state.profile))
    else:
        ui.propose(funds, source, omni.select, omni.decide)


funds, source, is_demo = ui.catalog()
ui.init_state(GREETING, "modelo único")
state = st.session_state

with st.sidebar:
    st.header("Modelo único")
    st.write("Un solo modelo multimodal recibe el audio, el texto o la imagen, decide qué preguntarte, "
             "fija los criterios y elige los fondos.")
    st.write(f"**Modelo:** {omni.LABEL if omni.available() else 'no descargado'}")
    st.write(f"**Datos:** {source}")
    st.write(f"**Voz de respuesta:** {tts.label()} (el modelo no genera voz)")
    st.caption("La primera respuesta tarda más: hay que cargar el modelo en la GPU.")
    if st.button("Nueva conversación"):
        state.clear()
        st.rerun()

st.title("FondoClaro · modelo único")
if not omni.available():
    st.error("Falta el modelo de esta versión. Ejecuta instalar_parte2_opcional.bat (necesita una tarjeta NVIDIA).")
    st.stop()
speak = ui.render_messages()

entry = ui.turn_input([suffix[1:] for suffix in AUDIO + IMAGES], speak)
if entry:
    started = time.perf_counter()
    text, clips = entry
    with tempfile.TemporaryDirectory() as folder:
        audio, images = [], []
        for index, clip in enumerate(clips):
            suffix = Path(clip.name).suffix.lower() or ".wav"
            payload = clip.getvalue()
            if suffix not in IMAGES and suffix not in AUDIO:  # browser recordings arrive as webm
                payload, suffix = to_wav(payload), ".wav"
            path = Path(folder) / f"entrada{index}{suffix}"
            path.write_bytes(payload)
            (images if suffix in IMAGES else audio).append(str(path))
        with st.spinner("Pensando..."):
            handle(text, audio, images, funds, source)
    state.messages[-1]["seconds"] = time.perf_counter() - started
    st.rerun()
