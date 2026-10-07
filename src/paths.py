"""Local paths and model identifiers shared by the app and the download script."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"

PRIVATE_CATALOG = ROOT / "data/private/funds.csv"
DEMO_CATALOG = ROOT / "data/demo_funds.csv"

# Voz -> texto
WHISPER_SIZE = os.getenv("WHISPER_MODEL", "small")
WHISPER_DIR = MODELS / "whisper" / WHISPER_SIZE

# Texto -> voz
PIPER_REPO = "rhasspy/piper-voices"
PIPER_FILE = "es/es_ES/davefx/medium/es_ES-davefx-medium.onnx"
PIPER_VOICE = MODELS / "piper" / PIPER_FILE

# Filtro con IA en GPU
GPU_LLM_REPO = "unsloth/gemma-3-4b-it"
GPU_LLM_PATH = MODELS / "llm-gpu" / "gemma-3-4b-it"

# Filtro con IA en CPU (respaldo sin GPU)
LLM_REPO = "unsloth/gemma-3-1b-it-GGUF"
LLM_FILE = "gemma-3-1b-it-Q4_K_M.gguf"
LLM_PATH = MODELS / "llm" / LLM_FILE

# Versión alternativa: un único modelo multimodal (texto, audio e imagen)
OMNI_REPO = "unsloth/gemma-3n-E2B-it"
OMNI_PATH = MODELS / "omni" / "gemma-3n-E2B-it"
