"""FondoClaro: punto de entrada. Una sola dirección con las dos versiones y las pruebas.

    streamlit run app.py        (o doble clic en iniciar.bat)
"""

from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)

st.set_page_config(page_title="FondoClaro · Asesor de fondos", page_icon="📊", layout="centered")
# El aspecto se edita en estilo.css (y los colores base en .streamlit/config.toml).
st.markdown(f"<style>{(ROOT / 'estilo.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

st.navigation({
    "Versiones": [
        st.Page("paginas/especialistas.py", title="Especialistas", icon="🧩", default=True),
        st.Page("paginas/modelo_unico.py", title="Modelo único", icon="🧠"),
    ],
    "Comprobaciones": [
        st.Page("paginas/pruebas.py", title="Pruebas y estado", icon="✅"),
    ],
}).run()
