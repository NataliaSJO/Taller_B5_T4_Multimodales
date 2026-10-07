"""Streamlit pieces shared by the two pages (specialised models and single multimodal model)."""

import base64
import os
import threading
from dataclasses import replace
from uuid import uuid4

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from . import brochures, history, screening, tts
from .catalog import load_catalog
from .conversation import THEMATIC, advise, apply_turn, describe, missing, question, valid_horizon, wants_more
from .models import MAX_HORIZON, Preferences
from .money import investment_allocation
from .preferences import ASSET_CLASSES, REGIONS, SECTORS
from .paths import BROCHURES, DEMO_CATALOG, PRIVATE_CATALOG, ROOT
from .report import DISCLAIMER, brief_summary, build_pdf, percents, summary_text

POOL = 150  # candidates handed to the selection step when there is no price history


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
    st.session_state.real_data = not is_demo   # price history and brochures only describe the real catalog
    return funds, source, is_demo


# What makes up one conversation. Each version keeps its own, so switching does not lose it.
CONVERSATION = ("messages", "profile", "pending", "relax", "extra_asked", "relaxed", "speak", "detail")


def new_conversation(greeting: str):
    state = st.session_state
    job = state.pop("job", None)
    if job is not None:
        job.stop.set()       # background work belongs to the conversation that is ending
    for key in CONVERSATION:
        state.pop(key, None)
    state.messages = [{"role": "assistant", "text": greeting, "audio": _spoken_greeting(greeting)}]
    state.speak = 0  # browsers may block sound before the first click; the player stays visible
    state.profile = Preferences()
    state.pending = ()


def init_state(greeting: str, version: str):
    """Open the conversation of this version, leaving the other version's where it was."""
    state = st.session_state
    current = state.get("version")
    if current == version and "messages" in state:
        return
    saved = state.setdefault("saved", {})
    if current is not None and "messages" in state:
        saved[current] = {key: state[key] for key in CONVERSATION if key in state and key != "speak"}
    state.version = version
    if version in saved:
        for key in CONVERSATION:
            state.pop(key, None)
        state.update(saved.pop(version))    # nothing is said aloud again when coming back
    else:
        new_conversation(greeting)


@st.cache_data(show_spinner=False)
def _spoken_greeting(greeting: str) -> bytes | None:
    return _voice(greeting)


def _voice(text: str) -> bytes | None:
    """Audio for a reply, or None: a voice failure must not cost the text, the table or the PDF."""
    try:
        return tts.synthesize(text)
    except Exception:
        return None


def warm_up(*loaders):
    """Load models in the background while the user is still talking, so the first answer does not
    pay for it. Each loader is tried once per server; failures are left for the real call to report."""
    started = _warm_started()
    for loader in loaders:
        name = getattr(loader, "__qualname__", repr(loader))
        if name not in started:
            started.add(name)
            threading.Thread(target=_quietly, args=(loader,), daemon=True).start()


@st.cache_resource
def _warm_started() -> set:
    return set()


def _quietly(loader):
    try:
        loader()
    except Exception:
        pass


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
                            play_id=len(state.messages), resume=state.get("resume", 0),
                            key="manos_libres", default=None)
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
    st.session_state.messages.append({"role": "assistant", "text": text, "audio": _voice(text), **extra})
    st.session_state.speak = len(st.session_state.messages) - 1


def show_latest(speak: int | None):
    """After a new answer, bring its beginning into view (the controls stay pinned below)."""
    if speak is None or speak == 0:
        return
    components.html(
        """<script>
        const messages = window.parent.document.querySelectorAll('[data-testid="stChatMessage"]');
        if (messages.length) messages[messages.length - 1].scrollIntoView({behavior: "smooth", block: "start"});
        </script>""", height=0)


def unheard():
    """A recording with no speech in it. Hands-free, that is usually a noise: keep listening
    without a word. Otherwise the client pressed the button, so say that nothing was heard."""
    state = st.session_state
    if state.get("modo", HANDS) == HANDS:
        state.resume = state.get("resume", 0) + 1
    else:
        say("No te he oído bien. ¿Puedes repetirlo?")


def user_turns() -> list[str]:
    return [message["text"] for message in st.session_state.messages if message["role"] == "user"]


def update_preferences(new: Preferences, text: str) -> bool:
    """Apply a turn consistently in both versions; False means a reply was sent."""
    state = st.session_state
    asked = tuple(state.get("relax", ()))
    state.profile, pending_relax, reply = apply_turn(
        state.profile, new, text, state.pending, asked)
    state.pending = missing(state.profile)
    if asked and not pending_relax and not reply:
        state.relaxed = asked        # the client agreed: the proposal will say what was dropped
    if pending_relax:
        state.relax = pending_relax
    else:
        state.pop("relax", None)
    if reply:
        say(reply)
    return not reply


def start_screening(funds, decide, shortlist):
    """Begin the proposal in the background while the adviser's questions are asked and answered."""
    state = st.session_state
    if not state.get("real_data") or state.pending:
        return
    profile, _ = advise(state.profile)
    job = state.get("job")
    if job is not None and job.key == screening.key_of(profile) and job.risk == profile.risk:
        return
    if job is not None:
        job.stop.set()
    state.job = screening.start(funds, profile, " ".join(user_turns()), decide, shortlist,
                                bool(state.get("documents")))


def detail_reply(text: str) -> bool:
    """After the short summary the client was asked whether they want the detail. True when this
    turn was the answer to that (and has been dealt with); False when they moved on to something else."""
    state = st.session_state
    detail = state.pop("detail", None)
    if detail is None:
        return False
    answer = wants_more(text)
    if answer is True:
        say(detail)
    elif answer is False:
        say("De acuerdo. Tienes la tabla y el informe en pantalla; si quieres cambiar algo, dímelo.")
    return answer is not None


def propose(funds, source: str, select, decide, shortlist=None):
    """All required data is known: filter, select, and build the PDF and the audio summary.

    `decide(profile, conversation)` returns the model's search criteria (or None) and
    `select(candidates, profile, conversation)` the Proposal; they are what differs between pages.
    Whatever a background job has already done for this profile is collected instead of redone.
    """
    state = st.session_state
    profile, notes = advise(state.profile)
    turns = user_turns()
    conversation = " ".join(turns)
    real = bool(state.get("real_data")) and history.available()
    progress = st.status("Decidiendo los criterios de búsqueda…")

    job = state.pop("job", None)
    prices, winners, screened = None, (), 0
    if job is not None and job.usable_for(profile):
        progress.update(label="Recogiendo lo que he ido adelantando mientras hablábamos…")
        job.finish()
    if job is not None and job.usable_for(profile):
        criteria, affinity = job.criteria_for(profile), job.affinity
        prices, winners, screened = job.prices, tuple(job.winners), job.screened
    else:
        if job is not None:
            job.stop.set()
        criteria = decide(profile, conversation)
        affinity = screening.affinity_for(profile, criteria, conversation) if state.get("documents") else {}
    theme = screening.theme_of(profile, criteria)

    progress.update(label=f"Buscando entre {len(funds):,} fondos…".replace(",", "."))
    candidates, diagnostics, criteria, dropped = screening.search(
        funds, profile, criteria, affinity, screening.WIDE if real else POOL)
    if dropped:
        notes.append(dropped)
    relaxed = state.pop("relaxed", None)
    if relaxed:
        names = {"region": "la zona", "sector": "el sector", "asset_class": "la clase de activo",
                 "excluded_sectors": "la exclusión de sectores"}
        notes.append("Como acordamos, he retirado " + " y ".join(names.get(field, field) for field in relaxed)
                     + " de la búsqueda porque ningún fondo lo cumplía con datos comprobables.")
    if diagnostics.get("reason") or not candidates:
        progress.update(label="Necesito una aclaración", state="complete")
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

    # With the daily history, funds that move together count as one: the model reads the best of
    # each group, so its list stands for many more funds than it has lines.
    lines, reviewed = candidates, None
    if real:
        progress.update(label=f"Leyendo el histórico diario de {len(candidates)} candidatos…")
        try:
            candidates = history.inform(candidates, profile, prices=prices)
            lines, represented, in_batches = screening.final_lines(candidates, winners, screened)
            reviewed = (len(lines), represented, in_batches)
        except Exception:      # the decision goes on with the catalog figures
            lines = candidates[:POOL]
    progress.update(label=f"Eligiendo entre {len(lines)} candidatos…")
    proposal = select(lines, profile, conversation)
    progress.update(label="Comprobando la cartera con el histórico diario…")
    analysis = None
    if state.get("real_data"):
        proposal = history.refine(proposal, lines, profile.horizon_years)
        try:
            analysis = history.analyse(proposal.items, proposal.weights, profile.horizon_years)
        except Exception:  # the report falls back to the illustrative simulation
            analysis = None
    try:
        investment_allocation(proposal.weights, profile.amount)
    except ValueError as exc:
        state.profile = replace(state.profile, amount=None, amount_needs_clarification=True)
        state.pending = missing(state.profile)
        say(str(exc))
        return
    how = criteria.describe() if criteria else ""
    others = brochures.without_history(state.get("documents") or {}, profile)
    progress.update(label="Preparando el informe y la voz…")
    try:
        pdf = build_pdf(proposal, profile, turns, source, notes, how, others, analysis)
    except Exception:   # the proposal is still shown and spoken
        pdf = None
    state.detail = summary_text(proposal, profile)
    say(brief_summary(proposal, profile, notes, analysis, sum(reviewed[1:]) if reviewed else 0), result={
        "proposal": proposal, "profile": profile, "eligible": diagnostics["eligible"], "criteria": how,
        "others": others, "excluded": {key: diagnostics.get(key, 0) for key in ("sri", "minimum")},
        "analysis": analysis, "pdf": pdf, "notes": notes, "reviewed": reviewed,
        "semantic": (len(affinity), theme) if affinity else None,
    })
    progress.update(label="Propuesta lista", state="complete")


def _show_result(message: dict, key: int):
    result, audio = message["result"], message.get("audio")
    proposal, profile = result["proposal"], result["profile"]
    years = profile.horizon_years
    rows = []
    allocation = investment_allocation(proposal.weights, profile.amount)
    for index, (item, share) in enumerate(zip(proposal.items, percents(allocation.weights, 2))):
        ret, vol, sharpe = item.fund.metrics(years)
        rows.append({"Fondo": item.fund.name, "ISIN/ID": item.fund.isin, "Peso aprox. (%)": float(share),
                     "Importe": float(allocation.amounts[index]) if allocation.amounts is not None else None,
                     f"Rent. {years} a. (%)": round(ret * 100, 1), "Volatilidad (%)": round(vol * 100, 1),
                     "Sharpe": None if sharpe is None else round(sharpe, 2),
                     "Riesgo oficial (1-7)": item.fund.sri, "Costes (%)": item.fund.costs})
    st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
        "Importe": st.column_config.NumberColumn(format="%.2f"),
        "Peso aprox. (%)": st.column_config.NumberColumn(format="%.2f"),
    })
    st.caption("Los porcentajes están redondeados; el informe y la simulación usan los importes asignados a céntimos.")
    st.caption(f"{result['eligible']} fondos superaron los filtros. Selección y pesos: {proposal.method}.")
    if result.get("criteria"):
        st.caption(f"Criterios decididos por el modelo y aplicados a todo el catálogo: {result['criteria']}.")
    analysis = result.get("analysis")
    if analysis:
        together = (f"; correlación media entre los fondos {analysis.mean_correlation:.2f}".replace(".", ",")
                    if analysis.mean_correlation is not None else "")
        figures = (f"una volatilidad anual del {analysis.volatility * 100:.1f} % y una caída máxima del "
                   f"{abs(analysis.max_drawdown) * 100:.1f} %").replace(".", ",")
        st.caption(f"Con el histórico diario de {analysis.weeks} semanas, la cartera en conjunto tuvo "
                   f"{figures}{together}.")
    if result.get("reviewed"):
        shown, represented, in_batches = result["reviewed"]
        st.caption(f"El modelo ha tenido en cuenta {represented + in_batches} fondos: ha leído {shown} líneas, una por "
                   f"cada grupo de fondos que se mueven muy parecido, que representan a {represented}"
                   + (f"; y otros {in_batches} los cribó por lotes mientras conversábamos." if in_batches else "."))
    if result.get("semantic"):
        found, theme = result["semantic"]
        st.caption(f"Búsqueda semántica en los folletos: {found} fondos con un objetivo afín"
                   + (f" a «{theme}»." if theme else " a lo que has contado."))
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
    for note in result.get("notes") or ():
        st.info(note)
    left, right = st.columns(2)
    if result.get("pdf"):
        left.download_button("📄 Descargar informe PDF", result["pdf"], file_name="propuesta_fondos.pdf",
                             mime="application/pdf", type="primary", key=f"pdf{key}")
    else:
        left.caption("No se ha podido generar el PDF; la propuesta completa está en esta página.")
    if audio:
        right.download_button("🔊 Descargar audio resumen", audio, file_name="resumen_fondos.wav",
                              mime="audio/wav", key=f"wav{key}")
    else:
        right.caption("No se ha podido generar el audio; el resumen está escrito arriba.")
    st.caption(DISCLAIMER)


def render_messages() -> int | None:
    """Draw the conversation. Returns the index of the answer still to be said aloud, if any."""
    state = st.session_state
    speak = state.pop("speak", None)
    hands_free = state.get("modo", HANDS) == HANDS  # there the component plays the answer itself
    # One container at a fixed place: what comes after it (the microphone) keeps its position
    # as the conversation grows, so the hands-free component is not restarted on every turn.
    latest = max((index for index, message in enumerate(state.messages) if message.get("result")), default=None)
    with st.container():
        for index, message in enumerate(state.messages):
            with st.chat_message(message["role"]):
                st.write(message["text"])
                if message.get("audio"):
                    st.audio(message["audio"], format="audio/wav", autoplay=index == speak and not hands_free)
                if message.get("result"):
                    if index == latest:
                        _show_result(message, index)
                    else:
                        with st.expander("Ver esta propuesta anterior"):
                            _show_result(message, index)
                if message.get("seconds") is not None:
                    st.caption(f"⏱ {message['seconds']:.1f} s en responder".replace(".", ","))
    return speak


OPTIONAL = "—"


def profile_panel(funds, source: str, select, decide):
    """Sidebar panel with what has been understood so far; the client can correct it by hand."""
    state = st.session_state
    profile: Preferences = state.profile
    token = abs(hash(profile))   # new widgets whenever the conversation changes the profile

    def choice(label: str, options, current):
        values = [OPTIONAL, *options]
        picked = st.selectbox(label, values, index=values.index(current) if current in values else 0,
                              key=f"perfil_{label}_{token}")
        return None if picked == OPTIONAL else picked

    with st.expander("Perfil interpretado (editable)", expanded=False):
        with st.form(f"perfil_{token}", border=False):
            years = st.number_input("Plazo (años)", min_value=0, max_value=MAX_HORIZON, step=1,
                                    value=profile.horizon_years if valid_horizon(profile.horizon_years) else 0,
                                    key=f"perfil_plazo_{token}", help="0 = sin indicar")
            risk = choice("Riesgo", ("bajo", "medio", "alto"), profile.risk)
            currency = choice("Divisa", sorted({fund.currency for fund in funds if fund.currency}), profile.currency)
            amount = st.number_input("Importe", min_value=0.0, step=500.0, value=float(profile.amount or 0.0),
                                     key=f"perfil_importe_{token}", help="0 = sin indicar")
            region = choice("Zona", tuple(REGIONS), profile.region)
            sector = choice("Sector", tuple(SECTORS), profile.sector)
            asset = choice("Clase de activo", tuple(ASSET_CLASSES), profile.asset_class)
            count = st.number_input("Número de fondos", min_value=0, max_value=7, step=1,
                                    value=profile.fund_count or 0, key=f"perfil_fondos_{token}",
                                    help="0 = según la diversificación")
            objective = choice("Objetivo", ("crecimiento", "preservación", "rentas"), profile.objective)
            experience = choice("Experiencia", ("baja", "alta"), profile.experience)
            reaction = choice("Ante una caída fuerte", ("vende", "espera", "compra"), profile.loss_reaction)
            if not st.form_submit_button("Aplicar cambios"):
                return
    state.profile = replace(
        profile, horizon_years=int(years) or None, risk=risk, currency=currency, amount=float(amount) or None,
        amount_needs_clarification=False, region=region, sector=sector, asset_class=asset,
        fund_count=int(count) or None, objective=objective, experience=experience, loss_reaction=reaction)
    state.pending = missing(state.profile)
    state.pop("relax", None)
    state.messages.append({"role": "user", "text": "He corregido mi perfil en el panel: " + (describe(state.profile) or "sin datos") + "."})
    if state.pending:
        say(question(state.profile))
    else:
        propose(funds, source, select, decide)
    st.rerun()
