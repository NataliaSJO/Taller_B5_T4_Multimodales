"""Streamlit pieces shared by the two pages (specialised models and single multimodal model)."""

import base64
import os
from dataclasses import replace
from uuid import uuid4

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from . import brochures, tts
from .catalog import load_catalog
from .conversation import THEMATIC, advise
from .models import Preferences
from .paths import BROCHURES, DEMO_CATALOG, PRIVATE_CATALOG, ROOT
from .recommender import recommend
from .report import DISCLAIMER, build_pdf, percents, summary_text

POOL = 150  # candidates handed to the selection step
MIN_CANDIDATES = 10  # fewer than this and the model's optional filters are dropped


@st.cache_resource(show_spinner="Cargando catálogo y folletos...")
def _catalog_at(path: str, modified_ns: int, brochures_ns: int):
    """Catalog funds, enriched with their documents when these have been processed."""
    funds = load_catalog(path)
    documents = brochures.load(BROCHURES) if brochures_ns else {}
    return (brochures.enrich(funds, documents) if documents else funds), documents


def catalog() -> tuple[list, str, bool]:
    # CATALOG=demo fuerza los fondos sintéticos (para demos y capturas sin datos con licencia)
    forced_demo = os.getenv("CATALOG", "").strip().lower() == "demo"
    path = PRIVATE_CATALOG if PRIVATE_CATALOG.is_file() and not forced_demo else DEMO_CATALOG
    is_demo = path == DEMO_CATALOG
    with_documents = BROCHURES.is_file() and not is_demo
    funds, documents = _catalog_at(str(path), path.stat().st_mtime_ns,
                                   BROCHURES.stat().st_mtime_ns if with_documents else 0)
    source = ("catálogo sintético de demostración" if is_demo
              else f"catálogo EODHD local ({len(funds):,} identificadores)".replace(",", "."))
    if documents:
        source += f" y documentación de {len(documents):,} fondos".replace(",", ".")
    st.session_state.documents = documents
    return funds, source, is_demo


def init_state(greeting: str, version: str):
    """Each version keeps its own conversation: changing version starts a new one."""
    state = st.session_state
    if state.get("version") != version:
        state.clear()
        state.version = version
        state.messages = [{"role": "assistant", "text": greeting, "audio": _spoken_greeting(greeting)}]
        state.speak = 0  # browsers may block sound before the first click; the player stays visible
        state.profile = Preferences()
        state.pending = ()


@st.cache_data(show_spinner=False)
def _spoken_greeting(greeting: str) -> bytes | None:
    return tts.synthesize(greeting)


HANDS, VOICE, CHAT = "🎧 Manos libres", "🎙️ Pulsar para hablar", "⌨️ Escribir"
# Browser side of the hands-free mode: speaks the answer, listens until the user stops talking and sends.
_hands_free = components.declare_component("manos_libres", path=str(ROOT / "componentes" / "manos_libres"))


class Clip:
    """A recording from the hands-free component, shaped like Streamlit's uploaded files."""

    def __init__(self, payload: bytes, name: str):
        self._payload, self.name = payload, name

    def getvalue(self) -> bytes:
        return self._payload


def turn_input(file_types: list[str], speak: int | None) -> tuple[str, list] | None:
    """The user's next turn as (text, audio or image files).

    Hands-free voice is the main way in; push-to-talk and chat are the alternatives.
    `speak` is the index of the assistant message that has not been said aloud yet, if any.
    """
    state = st.session_state
    mode = st.radio("Cómo quieres conversar", (HANDS, VOICE, CHAT), horizontal=True,
                    label_visibility="collapsed", key="modo")
    if mode == HANDS:
        reply = state.messages[speak].get("audio") if speak is not None else None
        heard = _hands_free(play=base64.b64encode(reply).decode() if reply else "",
                            play_id=len(state.messages), key="manos_libres", default=None)
        if heard and heard["id"] != state.get("heard"):
            state.heard = heard["id"]
            suffix = ".ogg" if "ogg" in heard["mime"] else ".mp4" if "mp4" in heard["mime"] else ".webm"
            return "", [Clip(base64.b64decode(heard["audio"]), "voz" + suffix)]
        return None
    if mode == VOICE:
        state.setdefault("mic", uuid4().hex)
        clip = st.audio_input("Pulsa el micrófono, habla y vuelve a pulsarlo para enviar", key=state.mic)
        if clip:
            state.mic = uuid4().hex  # a fresh recorder for the next turn
            return "", [clip]
        return None
    entry = st.chat_input("Escribe tu mensaje o adjunta un archivo", accept_file="multiple", file_type=file_types)
    return ((entry.text or "").strip(), list(entry.files or [])) if entry else None


def say(text: str, **extra):
    """Add an assistant turn; it is spoken aloud the next time the page is drawn."""
    st.session_state.messages.append({"role": "assistant", "text": text, "audio": tts.synthesize(text), **extra})
    st.session_state.speak = len(st.session_state.messages) - 1


def user_turns() -> list[str]:
    return [message["text"] for message in st.session_state.messages if message["role"] == "user"]


def propose(funds, source: str, select, decide):
    """All required data is known: filter, select, and build the PDF and the audio summary.

    `decide(profile, conversation)` returns the model's search criteria (or None) and
    `select(candidates, profile, conversation)` the Proposal; they are what differs between pages.
    """
    state = st.session_state
    profile, notes = advise(state.profile)
    turns = user_turns()
    criteria = decide(profile, " ".join(turns))
    candidates, diagnostics = recommend(funds, profile, limit=POOL, criteria=criteria)
    if criteria and len(candidates) < MIN_CANDIDATES and (criteria.keywords or criteria.min_annual_return):
        # The model's optional filters left too few funds: keep its weights and target only.
        criteria = replace(criteria, keywords=(), min_annual_return=None)
        candidates, diagnostics = recommend(funds, profile, limit=POOL, criteria=criteria)
    if diagnostics.get("reason"):
        state.relax = ("excluded_sectors",)
        say("No puedo garantizar exclusiones por sector porque el catálogo no trae la composición completa "
            "de cada fondo. ¿Quieres que siga sin esa exclusión?")
        return
    if not candidates:
        thematic = tuple(field for field in THEMATIC if getattr(profile, field))
        if thematic and diagnostics["risk"]:
            state.relax = thematic
            wanted = ", ".join(getattr(profile, field) for field in thematic)
            say(f"Hay {diagnostics['risk']} fondos que cumplen divisa, plazo y riesgo, pero ninguno encaja con "
                f"la preferencia que pides: {wanted}. ¿Quieres que la quite y te proponga fondos sin ese filtro?")
        else:
            say(f"No encuentro fondos en {profile.currency} con datos suficientes a {profile.horizon_years} años "
                f"y riesgo {profile.risk}. Dime otra divisa, otro plazo u otro nivel de riesgo y lo vuelvo a intentar.")
        return
    proposal = select(candidates, profile, " ".join(turns))
    how = criteria.describe() if criteria else ""
    others = brochures.without_history(state.get("documents") or {}, profile)
    say(summary_text(proposal, profile, notes), result={
        "proposal": proposal, "profile": profile, "eligible": diagnostics["eligible"], "criteria": how,
        "others": others, "excluded": {key: diagnostics[key] for key in ("sri", "minimum")},
        "pdf": build_pdf(proposal, profile, turns, source, notes, how, others),
    })


def _show_result(message: dict, key: int):
    result, audio = message["result"], message.get("audio")
    proposal, profile = result["proposal"], result["profile"]
    years = profile.horizon_years
    rows = []
    for item, share in zip(proposal.items, percents(proposal.weights)):
        ret, vol, sharpe = item.fund.metrics(years)
        rows.append({"Fondo": item.fund.name, "ISIN/ID": item.fund.isin, "Peso (%)": share,
                     "Importe": round(profile.amount * share / 100) if profile.amount else None,
                     f"Rent. {years} a. (%)": round(ret * 100, 1), "Volatilidad (%)": round(vol * 100, 1),
                     "Sharpe": None if sharpe is None else round(sharpe, 2),
                     "Riesgo oficial (1-7)": item.fund.sri, "Costes (%)": item.fund.costs})
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    st.caption(f"{result['eligible']} fondos superaron los filtros. Selección y pesos: {proposal.method}.")
    if result.get("criteria"):
        st.caption(f"Criterios decididos por el modelo y aplicados a todo el catálogo: {result['criteria']}.")
    excluded = result.get("excluded") or {}
    if excluded.get("sri") or excluded.get("minimum"):
        st.caption(f"Descartados por su documentación: {excluded['sri']} por riesgo oficial superior al perfil "
                   f"y {excluded['minimum']} por inversión mínima superior al importe.")
    if result.get("others"):
        with st.expander("Otros fondos con folleto que encajan, sin histórico de precios"):
            st.dataframe(pd.DataFrame([{"Fondo": doc.name, "ISIN": doc.isin, "Riesgo oficial (1-7)": doc.sri,
                                        "Costes (%)": doc.costs, "Categoría": doc.category or doc.assets}
                                       for doc in result["others"]]), hide_index=True)
            st.caption("No están en el catálogo de precios, así que no se pueden puntuar ni incluir en el reparto.")
    left, right = st.columns(2)
    left.download_button("📄 Descargar informe PDF", result["pdf"], file_name="propuesta_fondos.pdf",
                         mime="application/pdf", type="primary", key=f"pdf{key}")
    if audio:
        right.download_button("🔊 Descargar audio resumen", audio, file_name="resumen_fondos.wav",
                              mime="audio/wav", key=f"wav{key}")
    st.caption(DISCLAIMER)


def render_messages() -> int | None:
    """Draw the conversation. Returns the index of the answer still to be said aloud, if any."""
    state = st.session_state
    speak = state.pop("speak", None)
    hands_free = state.get("modo", HANDS) == HANDS  # there the component plays the answer itself
    # One container at a fixed place: what comes after it (the microphone) keeps its position
    # as the conversation grows, so the hands-free component is not restarted on every turn.
    with st.container():
        for index, message in enumerate(state.messages):
            with st.chat_message(message["role"]):
                st.write(message["text"])
                if message.get("audio"):
                    st.audio(message["audio"], format="audio/wav", autoplay=index == speak and not hands_free)
                if message.get("result"):
                    _show_result(message, index)
                if message.get("seconds") is not None:
                    st.caption(f"⏱ {message['seconds']:.1f} s en responder".replace(".", ","))
    return speak
