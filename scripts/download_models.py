"""Download the local models from Hugging Face into models/ (ignored by Git).

Sin argumentos: Whisper base (voz a texto), una voz Piper en castellano (texto a voz) y
Gemma 3 1B cuantizado (filtro en CPU). Alrededor de 1 GB.

    --gpu    añade Gemma 3 4B (8 GB) para el filtro en GPU
    --omni   añade Gemma 3n E2B (11 GB) para la versión de modelo único

Gemma se distribuye bajo los términos de uso de Google.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faster_whisper import download_model
from huggingface_hub import hf_hub_download, snapshot_download

from src.paths import (GPU_LLM_PATH, GPU_LLM_REPO, LLM_FILE, LLM_PATH, LLM_REPO, MODELS, OMNI_PATH, OMNI_REPO,
                       PIPER_FILE, PIPER_REPO, WHISPER_DIR, WHISPER_SIZE)

WEIGHTS = ["*.safetensors", "*.json", "*.model", "*.txt", "*.jinja"]


def main() -> None:
    print(f"Whisper {WHISPER_SIZE} -> {WHISPER_DIR}")
    download_model(WHISPER_SIZE, output_dir=str(WHISPER_DIR))
    for filename in (PIPER_FILE, PIPER_FILE + ".json"):
        print(f"Piper {filename}")
        hf_hub_download(PIPER_REPO, filename, local_dir=MODELS / "piper")
    print(f"Gemma {LLM_FILE}")
    hf_hub_download(LLM_REPO, LLM_FILE, local_dir=LLM_PATH.parent)
    if "--gpu" in sys.argv:
        print(f"Gemma 3 4B -> {GPU_LLM_PATH}")
        snapshot_download(GPU_LLM_REPO, local_dir=GPU_LLM_PATH, allow_patterns=WEIGHTS)
    if "--omni" in sys.argv:
        print(f"Gemma 3n -> {OMNI_PATH}")
        snapshot_download(OMNI_REPO, local_dir=OMNI_PATH, allow_patterns=WEIGHTS)
    print("Modelos listos en", MODELS)


if __name__ == "__main__":
    main()
