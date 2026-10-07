"""Estado de la instalación y pruebas automáticas, ejecutables desde el navegador."""

import subprocess
import sys

import streamlit as st

from src import ai_filter, hf_model, omni, tts
from src.paths import GPU_LLM_PATH, LLM_PATH, OMNI_PATH, PIPER_VOICE, PRIVATE_CATALOG, ROOT, WHISPER_DIR

st.title("Pruebas y estado")

st.subheader("Qué hay instalado")
checks = [
    ("Catálogo real importado", PRIVATE_CATALOG.is_file(), "python scripts/import_catalog.py <catalogo_fondos.md>"),
    ("Whisper (voz a texto)", (WHISPER_DIR / "model.bin").is_file(), "python scripts/download_models.py"),
    ("Piper (texto a voz)", tts.available(), "python scripts/download_models.py"),
    ("Gemma 3 1B (filtro en CPU)", LLM_PATH.is_file(), "python scripts/download_models.py"),
    ("Gemma 3 4B (filtro en GPU)", (GPU_LLM_PATH / "config.json").is_file(), "python scripts/download_models.py --gpu"),
    ("Gemma 3n (modelo único)", omni.available(), "python scripts/download_models.py --omni"),
    ("GPU con CUDA", hf_model.gpu_available(), "Sin GPU funcionan el filtro en CPU y las reglas"),
    ("Clave de Claude (opcional)", ai_filter.available("claude"), "ANTHROPIC_API_KEY en .env; deshabilitado por defecto"),
]
st.dataframe([{"Componente": name, "Estado": "✅ disponible" if ok else "— falta", "Cómo obtenerlo": "" if ok else how}
              for name, ok, how in checks], hide_index=True)
st.caption(f"Filtro que se usará por defecto: {ai_filter.label()}.")

st.subheader("Pruebas automáticas")
st.write("Comprueban el diálogo, los filtros, la validación de las respuestas del modelo y la generación del PDF. "
         "Incluyen los flujos de ambas páginas con modelos simulados. No cargan modelos reales y pueden tardar varios segundos.")
if st.button("Ejecutar pruebas", type="primary"):
    run = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                         cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if run.returncode == 0:
        st.success("Todas las pruebas pasan.")
    else:
        st.error("Hay pruebas que fallan.")
    st.code(run.stderr or run.stdout, language=None)

st.subheader("Conversación de prueba")
st.write("Usa la misma en las dos versiones para compararlas:")
st.markdown("1. «Quiero invertir 10.000 euros en fondos de tecnología, bien diversificado»\n"
            "2. «A cinco años y riesgo alto»\n"
            "3. «Quiero hacer crecer el dinero, nunca he invertido y si cae vendería»")
