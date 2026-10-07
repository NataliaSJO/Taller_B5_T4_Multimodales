"""Versión por especialistas: Whisper oye, reglas extraen, Gemma elige, Piper habla."""

import os
import time
from pathlib import Path

import streamlit as st

from src import ai_filter, tts, ui
from src.audio import AUDIO_TYPES, transcribe_audio
from src.conversation import GREETING, extra_question, is_yes, merge, missing, parse_turn, question, relax

RULES, MODEL = "Reglas", "Reglas + modelo de lenguaje"
FILTERS = {"gpu": "Gemma 3 4B en GPU", "local": "Gemma 3 1B en CPU", "claude": "Claude por API", "off": "Solo reglas"}


def handle(text: str, funds, source: str):
    state = st.session_state
    state.messages.append({"role": "user", "text": text})
    pending_relax = state.pop("relax", None)
    if pending_relax and is_yes(text):
        state.profile = relax(state.profile, pending_relax)
    else:
        history = [(message["role"], message["text"]) for message in state.messages[:-1]]
        read = ai_filter.understand(history, state.profile, text) if state.get("lector") == MODEL else None
        if read:  # the rules have the last word where both found something
            state.profile = merge(state.profile, read[0])
        state.profile = merge(state.profile, parse_turn(text, state.pending))
    state.pending = missing(state.profile)
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
    st.radio("Quién entiende lo que dices", (RULES, MODEL), key="lector", disabled=chosen not in ("gpu", "claude"),
             help="Las reglas son instantáneas. El modelo entiende frases más libres, tarda unos segundos "
                  "y puede equivocarse; las reglas tienen la última palabra donde ambos encuentran un dato.")
    st.write(f"**Datos:** {source}")
    st.write(f"**Voz de respuesta:** {tts.label()}")
    if st.button("Nueva conversación"):
        state.clear()
        st.rerun()

st.title("FondoClaro")
if is_demo:
    st.warning("**Modo demostración:** los 10 fondos y sus cifras son sintéticos.")
speak = ui.render_messages()

entry = ui.turn_input(AUDIO_TYPES, speak)
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
    with st.spinner("Pensando..."):
        if text:
            handle(text, funds, source)
        else:  # said aloud so that a hands-free conversation keeps going
            ui.say("No te he oído bien. ¿Puedes repetirlo?")
    state.messages[-1]["seconds"] = time.perf_counter() - started
    st.rerun()
