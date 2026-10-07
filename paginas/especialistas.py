"""Versión por especialistas: Whisper oye, reglas extraen, Gemma elige, Piper habla."""

import os
import time
from pathlib import Path

import streamlit as st

from src import ai_filter, audio, tts, ui
from src.audio import AUDIO_TYPES, transcribe_audio
from src.conversation import GREETING, extra_question, merge, parse_turn, question

RULES, MODEL = "Reglas", "Reglas + modelo de lenguaje"
FILTERS = {"gpu": "Gemma 3 4B en GPU", "local": "Gemma 3 1B en CPU", "claude": "Claude por API", "off": "Solo reglas"}


def handle(text: str, funds, source: str):
    state = st.session_state
    state.messages.append({"role": "user", "text": text})
    new = parse_turn(text, state.pending)
    if state.get("lector") == MODEL:
        history = [(message["role"], message["text"]) for message in state.messages[:-1]]
        read = ai_filter.understand(history, state.profile, text)
        if read:  # the rules have the last word where both found something
            new = merge(read[0], new)
    if not ui.update_preferences(new, text):
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
             "un modelo de lenguaje decide los criterios y elige los fondos, y una voz sintética responde.")
    options = [name for name in FILTERS if ai_filter.available(name)]
    chosen = st.selectbox("Quién elige los fondos", options, index=options.index(ai_filter.backend()),
                          format_func=FILTERS.get, help="Solo aparecen las opciones instaladas en este equipo.")
    os.environ["AI_FILTER"] = chosen
    st.radio("Quién entiende lo que dices", (RULES, MODEL), key="lector", disabled=chosen not in ("gpu", "claude"),
             help="Las reglas son instantáneas. El modelo entiende frases más libres, tarda unos segundos "
                  "y puede equivocarse; las reglas tienen la última palabra donde ambos encuentran un dato.")
    st.write(f"**Datos:** {source}")
    st.write(f"**Voz a texto:** {audio.label()}")
    st.write(f"**Voz de respuesta:** {tts.label()}")
    if st.button("Nueva conversación"):
        ui.new_conversation(GREETING)
        st.rerun()
    ui.profile_panel(funds, source, ai_filter.select, ai_filter.decide)

# While the user is still talking, load what the first answer will need.
if not is_demo:
    ui.warm_up(audio.warm, *((ai_filter.warm,) if chosen == "gpu" else ()))

st.title("FondoClaro")
if is_demo:
    st.warning("**Modo demostración:** los 10 fondos y sus cifras son sintéticos.")
speak = ui.render_messages()

entry = ui.turn_input(AUDIO_TYPES, speak)
ui.show_latest(speak)
if entry:
    started = time.perf_counter()
    text, clips = entry
    try:
        with st.spinner("Transcribiendo con Whisper local..."):
            spoken = [transcribe_audio(clip.getvalue(), Path(clip.name).suffix or ".wav") for clip in clips]
    except Exception as exc:   # an unreadable recording: the conversation goes on
        spoken, text = [], ""
        st.session_state.audio_error = str(exc)
    text = " ".join(part for part in (*spoken, text) if part).strip()
    with st.spinner("Pensando..."):
        try:
            if text:
                handle(text, funds, source)
            else:
                ui.unheard()
        except Exception as exc:   # nothing may leave the conversation without an answer
            ui.say(f"He tenido un problema al preparar la respuesta ({type(exc).__name__}). "
                   "Lo que me has dicho está guardado; puedes repetirlo o corregir el perfil en el panel lateral.")
    if text:
        state.messages[-1]["seconds"] = time.perf_counter() - started
    st.rerun()
