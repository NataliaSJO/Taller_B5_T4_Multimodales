"""FondoClaro: an explainable, multimodal fund shortlist MVP."""

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from streamlit.components.v1 import html

from src.audio import transcribe_audio
from src.catalog import load_catalog
from src.models import Preferences
from src.preferences import parse_with_optional_llm
from src.recommender import recommend

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)
PRIVATE = ROOT / "data/private/funds.csv"
DEMO = ROOT / "data/demo_funds.csv"

st.set_page_config(page_title="FondoClaro · Recomendador de fondos", page_icon="📊", layout="wide")
st.markdown("""
<style>
    .block-container {max-width: 1150px; padding-top: 2rem;}
    h1, h2, h3 {color: #173553;}
    [data-testid="stMetric"] {background: #f1f6f8; padding: 0.7rem 1rem; border-radius: 0.6rem;}
</style>
""", unsafe_allow_html=True)


@st.cache_data(show_spinner="Cargando catálogo...")
def catalog_at(path: str, modified_ns: int):
    return load_catalog(path)


def fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.1%}".replace(".", ",")


def fmt_vol(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}".replace(".", ",")


def fmt_sharpe(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2f}".replace(".", ",")


def audio_button(message: str):
    safe = json.dumps(message, ensure_ascii=False).replace("<", "\\u003c")
    html(f"""
    <button style="border:0;border-radius:8px;background:#087f8c;color:white;padding:9px 15px;cursor:pointer"
      onclick="window.speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance({safe}); u.lang='es-ES'; window.speechSynthesis.speak(u)">
      🔊 Escuchar resumen
    </button>
    """, height=48)


path = PRIVATE if PRIVATE.is_file() else DEMO
funds = catalog_at(str(path), path.stat().st_mtime_ns)
is_demo = path == DEMO

st.title("FondoClaro")
st.write("Describe con tus palabras qué buscas y obtén una **preselección razonada de fondos**.")
if is_demo:
    st.warning("**Modo demostración:** los 10 fondos y sus cifras son sintéticos. Importa el catálogo privado para explorar los datos EODHD reales.")
else:
    st.success(f"Catálogo privado cargado: {len(funds):,} identificadores. Los datos permanecen en este equipo.")

with st.sidebar:
    st.header("Cómo funciona")
    st.write("1. Texto o voz → preferencias explícitas.\n\n2. Confirmas el perfil extraído.\n\n3. Filtros y puntuación reproducibles → propuesta con métricas y límites.")
    st.divider()
    st.write(f"**Fuente activa:** {'ejemplo sintético' if is_demo else 'catálogo local privado'}")
    st.write("**Corte de datos:** 05/10/2026")
    st.write("**Riesgo:** bajo ≤10 % vol.; medio ≤20 %; alto ≤35 %. Son umbrales del prototipo, no categorías oficiales.")
    st.caption("El modelo de lenguaje, si se activa, solo extrae preferencias. Nunca elige productos ni inventa métricas.")

tab_recommend, tab_method = st.tabs(["Recomendación", "Datos y método"])

with tab_recommend:
    st.subheader("1. Tu petición")
    if "pending_transcript" in st.session_state:
        st.session_state.request_text = st.session_state.pop("pending_transcript")
    if "request_text" not in st.session_state:
        st.session_state.request_text = ""
    st.text_area("Escribe en lenguaje natural", key="request_text", height=110,
                 placeholder="Quiero invertir en euros a 5 años, con riesgo medio y preferencia por fondos globales")
    with st.expander("También puedes hablar"):
        recorded = st.audio_input("Graba tu petición")
        uploaded = st.file_uploader("O carga un WAV, MP3 o M4A", type=["wav", "mp3", "m4a"])
        selected_audio = recorded or uploaded
        if selected_audio and st.button("Transcribir audio"):
            try:
                with st.spinner("Transcribiendo con Whisper local..."):
                    transcript = transcribe_audio(selected_audio.getvalue(), Path(selected_audio.name).suffix or ".wav")
                if not transcript:
                    st.error("No se detectó voz inteligible. Prueba otro audio.")
                else:
                    st.session_state.pending_transcript = transcript
                    st.rerun()
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
    llm_available = bool(os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY"))
    use_llm = st.checkbox("Interpretar con modelo de lenguaje (opcional)", disabled=not llm_available,
                          help="Requiere OPENROUTER_API_KEY u OPENAI_API_KEY y requirements-ai.txt. Envía solo el texto de tu petición al proveedor elegido; el catálogo permanece local. Sin clave se usan reglas locales.")
    if st.button("Interpretar petición", type="primary"):
        text = st.session_state.request_text.strip()
        if not text:
            st.error("Escribe o transcribe una petición antes de continuar.")
        else:
            profile, method = parse_with_optional_llm(text, use_llm=use_llm)
            st.session_state.profile = profile
            st.session_state.method = method
            st.session_state.pop("recommendations", None)

    profile = st.session_state.get("profile")
    if profile is not None:
        st.subheader("2. Confirma el perfil")
        st.caption(f"Interpretación: {st.session_state.get('method', 'Reglas locales')}. Puedes corregir cualquier campo.")
        with st.form("profile_form"):
            c1, c2, c3 = st.columns(3)
            horizon_options = ["Selecciona...", 1, 3, 5]
            horizon_index = horizon_options.index(profile.horizon_years) if profile.horizon_years in horizon_options else 0
            risk_options = ["Selecciona...", "bajo", "medio", "alto"]
            risk_index = risk_options.index(profile.risk) if profile.risk in risk_options else 0
            currencies = ["Selecciona...", *sorted({fund.currency for fund in funds if fund.currency})]
            currency_index = currencies.index(profile.currency) if profile.currency in currencies else 0
            horizon = c1.selectbox("Horizonte (años)", horizon_options, index=horizon_index)
            risk = c2.selectbox("Riesgo declarado", risk_options, index=risk_index)
            currency = c3.selectbox("Divisa de la clase", currencies, index=currency_index)
            c4, c5, c6 = st.columns(3)
            region_options = ["Sin preferencia", "global", "europa", "estados unidos", "asia", "emergentes"]
            sector_options = ["Sin preferencia", "tecnología", "salud", "energía", "finanzas"]
            asset_options = ["Sin preferencia", "renta fija", "renta variable", "mixto", "monetario"]
            region = c4.selectbox("Región", region_options,
                                  index=region_options.index(profile.region) if profile.region in region_options else 0)
            sector = c5.selectbox("Sector", sector_options,
                                  index=sector_options.index(profile.sector) if profile.sector in sector_options else 0)
            asset_class = c6.selectbox("Clase de activo", asset_options,
                                       index=asset_options.index(getattr(profile, "asset_class", None))
                                       if getattr(profile, "asset_class", None) in asset_options else 0)
            st.write(f"**Importe detectado:** {profile.amount:,.2f} €" if profile.amount is not None and profile.currency == "EUR" else
                     f"**Importe detectado:** {profile.amount:,.2f}" if profile.amount is not None else "**Importe:** no indicado")
            st.write(f"**Exclusiones detectadas:** {', '.join(profile.excluded_sectors) or 'ninguna'}")
            submitted = st.form_submit_button("Obtener propuesta", type="primary")
        if submitted:
            confirmed = Preferences(
                horizon_years=horizon if isinstance(horizon, int) else None,
                risk=risk if risk != "Selecciona..." else None,
                currency=currency if currency != "Selecciona..." else None,
                amount=profile.amount,
                region=region if region != "Sin preferencia" else None,
                sector=sector if sector != "Sin preferencia" else None,
                excluded_sectors=profile.excluded_sectors,
                asset_class=asset_class if asset_class != "Sin preferencia" else None,
            )
            try:
                results, diagnostics = recommend(funds, confirmed)
                st.session_state.recommendations = (results, diagnostics, confirmed)
            except ValueError as exc:
                st.error(str(exc))

    if "recommendations" in st.session_state:
        results, diagnostics, confirmed = st.session_state.recommendations
        st.subheader("3. Propuesta razonada")
        if diagnostics.get("reason"):
            st.warning(diagnostics["reason"])
        elif not results:
            st.warning("No hay fondos que cumplan estos criterios con datos suficientes. Reduce los filtros o elige otro horizonte; no se inventan exposiciones ni métricas faltantes.")
            st.caption(f"Tras divisa: {diagnostics['currency']:,}; con métricas recientes: {diagnostics['metrics']:,}; "
                       f"dentro del límite de riesgo: {diagnostics['risk']:,}; con preferencias verificadas: {diagnostics['profile']:,}.")
        else:
            eligible = diagnostics["eligible"]
            st.caption(
                f"{eligible} {'candidato superó' if eligible == 1 else 'candidatos superaron'} los filtros del catálogo. "
                + ("Mostramos el mejor puntuado." if len(results) == 1
                   else f"Mostramos los {len(results)} mejor puntuados.")
            )
            table = []
            for item in results:
                ret, vol, sharpe = item.fund.metrics(confirmed.horizon_years)
                table.append({"Fondo": item.fund.name, "ISIN/ID": item.fund.isin,
                              "Divisa": item.fund.currency, "Rentabilidad": fmt_pct(ret),
                              "Volatilidad": fmt_vol(vol), "Sharpe": fmt_sharpe(sharpe),
                              "Puntuación": round(item.score, 3)})
            st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
            chart_data = pd.DataFrame([
                {"Fondo": item.fund.name,
                 "1 año": item.fund.return_1y * 100 if item.fund.return_1y is not None else None,
                 "3 años": item.fund.return_3y * 100 if item.fund.return_3y is not None else None,
                 "5 años": item.fund.return_5y * 100 if item.fund.return_5y is not None else None}
                for item in results
            ]).set_index("Fondo")
            st.caption("Rentabilidad acumulada histórica (%) por plazo. Los datos ausentes no se representan.")
            st.bar_chart(chart_data)
            for index, item in enumerate(results, start=1):
                with st.expander(f"{index}. {item.fund.name} · {item.fund.isin}"):
                    st.write(item.rationale)
                    st.write(f"**Estrategia:** {item.fund.strategy or 'sin fuente verificada'}")
                    st.write(f"**Activos:** {item.fund.assets or 'sin fuente verificada'}")
                    st.write(f"**Regiones:** {item.fund.regions or 'sin fuente verificada'}")
                    st.write(f"**Sectores:** {item.fund.sectors or 'sin fuente verificada'}")
                    st.write(f"**Último dato de precio:** {item.fund.last_date}")
                    if item.fund.source_url and item.fund.source_url.startswith("https://"):
                        st.markdown(f"[Ficha externa asociada al ISIN]({item.fund.source_url})")
            summary = (f"Propuesta orientativa para perfil {confirmed.risk}, horizonte de {confirmed.horizon_years} años "
                       f"y divisa {confirmed.currency}. Primer candidato: {results[0].fund.name}. "
                       f"{results[0].rationale} Contrasta el folleto y las comisiones antes de decidir.")
            audio_button(summary)
            st.download_button("Descargar propuesta CSV", pd.DataFrame(table).to_csv(index=False).encode("utf-8-sig"),
                               file_name="propuesta_fondos.csv", mime="text/csv")
        st.info("Es una preselección educativa basada en datos históricos. No sustituye un test de idoneidad ni verifica comisiones, situación personal o todos los riesgos del producto.")

with tab_method:
    st.subheader("Método y procedencia")
    st.write("El catálogo privado se genera a partir del Markdown EODHD. La app no consulta ni publica las claves API ni el dataset completo. El CSV incluido en el repo contiene solo fondos ficticios para una demo inmediata.")
    st.write("**Orden de decisión:** misma divisa → datos completos y recientes → límite de volatilidad del perfil → región, sector o clase de activo con fuente explícita, si se solicitaron → puntuación por ajuste de riesgo (55 %), Sharpe (25 %) y rentabilidad anual equivalente (20 %).")
    st.write("La rentabilidad es acumulada; la volatilidad y Sharpe están anualizados. Un Sharpe vacío no se sustituye por cero. Las cifras históricas no predicen rendimientos futuros.")
    st.write("La voz se transcribe con Whisper local si se instala el complemento; el modelo de lenguaje opcional extrae parámetros estructurados. El motor de ranking es determinista y auditable. La síntesis de voz utiliza el navegador.")
    st.markdown("Consulta el [README del proyecto](https://github.com/NataliaSJO/Taller_B5_T4_Multimodales) para instalar, importar el catálogo y ejecutar la demo.")
