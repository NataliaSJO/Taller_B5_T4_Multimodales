"""Versión alternativa: un único modelo multimodal (Gemma 3n) oye, entiende, pregunta y elige."""

import tempfile
import time
from pathlib import Path

import streamlit as st

from src import omni, tts, ui
from src.conversation import GREETING, extra_question, question

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
    if not ui.update_preferences(new, transcript or text):
        return
    if state.pending:
        ui.say(question(state.profile))
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
    st.write(f"**Voz de respuesta:** {'Piper local (el modelo no genera voz)' if tts.available() else 'no instalada'}")
    st.caption("La primera respuesta tarda más: hay que cargar el modelo en la GPU.")
    if st.button("Nueva conversación"):
        state.clear()
        st.rerun()

st.title("FondoClaro · modelo único")
if not omni.available():
    st.error("Falta el modelo. Descárgalo con: python scripts/download_models.py --omni")
    st.stop()
ui.render_messages()

entry = ui.turn_input([suffix[1:] for suffix in AUDIO + IMAGES])
if entry:
    started = time.perf_counter()
    text, clips = entry
    with tempfile.TemporaryDirectory() as folder:
        audio, images = [], []
        for index, clip in enumerate(clips):
            suffix = Path(clip.name).suffix.lower() or ".wav"
            path = Path(folder) / f"entrada{index}{suffix}"
            path.write_bytes(clip.getvalue())
            (images if suffix in IMAGES else audio).append(str(path))
        with st.spinner("Pensando..."):
            handle(text, audio, images, funds, source)
    state.messages[-1]["seconds"] = time.perf_counter() - started
    st.rerun()
