"""Versión por especialistas: Whisper oye, reglas extraen, Gemma elige, Piper habla."""

import os
import time
from pathlib import Path

import streamlit as st

from src import ai_filter, tts, ui
from src.audio import AUDIO_TYPES, transcribe_audio
from src.conversation import GREETING, extra_question, parse_turn, question

FILTERS = {"gpu": "Gemma 3 4B en GPU", "local": "Gemma 3 1B en CPU", "claude": "Claude por API", "off": "Solo reglas"}


def handle(text: str, funds, source: str):
    state = st.session_state
    state.messages.append({"role": "user", "text": text})
    if not ui.update_preferences(parse_turn(text, state.pending), text):
        return
    extra = None if state.pending or state.get("extra_asked") else extra_question(state.profile)
    if state.pending:
        ui.say(question(state.profile))
    elif extra:
        state.extra_asked = True
        ui.say(extra)
    else:
        ui.propose(funds, source, ai_filter.select, ai_filter.decide)


funds, source, is_demo = ui.catalog()
ui.init_state(GREETING, "especialistas")
state = st.session_state

with st.sidebar:
    st.header("Especialistas")
    st.write("Un modelo adaptado a cada paso: Whisper transcribe, unas reglas extraen los datos, "
             "un modelo de lenguaje decide los criterios y elige los fondos, y Piper habla.")
    options = [name for name in FILTERS if ai_filter.available(name)]
    chosen = st.selectbox("Quién elige los fondos", options, index=options.index(ai_filter.backend()),
                          format_func=FILTERS.get, help="Solo aparecen las opciones instaladas en este equipo.")
    os.environ["AI_FILTER"] = chosen
    st.write(f"**Datos:** {source}")
    st.write(f"**Voz de respuesta:** {'Piper local' if tts.available() else 'no instalada'}")
    if st.button("Nueva conversación"):
        state.clear()
        st.rerun()

st.title("FondoClaro")
if is_demo:
    st.warning("**Modo demostración:** los 10 fondos y sus cifras son sintéticos.")
ui.render_messages()

entry = ui.turn_input(AUDIO_TYPES)
if entry:
    started = time.perf_counter()
    text, clips = entry
    try:
        with st.spinner("Transcribiendo con Whisper local..."):
            spoken = [transcribe_audio(clip.getvalue(), Path(clip.name).suffix or ".wav") for clip in clips]
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        st.stop()
    text = " ".join(part for part in (*spoken, text) if part).strip()
    if not text:
        st.error("No se detectó voz inteligible. Prueba de nuevo.")
        st.stop()
    with st.spinner("Pensando..."):
        handle(text, funds, source)
    state.messages[-1]["seconds"] = time.perf_counter() - started
    st.rerun()
