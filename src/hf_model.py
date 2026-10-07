"""Run a local Hugging Face Gemma model with PyTorch, on the GPU when there is one."""

import gc
import json
import sys
import threading
import types
from pathlib import Path

# One model in memory at a time and one request at a time, so every version fits on the same card.
# Kept outside this module's globals because Streamlit re-imports edited modules, which would
# otherwise orphan a loaded model on the GPU.
_gpu = sys.modules.setdefault("_fondoclaro_gpu", types.SimpleNamespace(loaded={}, lock=threading.Lock()))


def gpu_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return torch.cuda.is_available()


def _load(path: str, four_bit: bool):
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    if (path, four_bit) in _gpu.loaded:
        return _gpu.loaded[path, four_bit]
    _gpu.loaded.clear()  # switching version frees the other model before loading
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    processor = AutoProcessor.from_pretrained(path)
    options = {"dtype": torch.bfloat16, "device_map": "cuda" if torch.cuda.is_available() else "cpu"}
    if four_bit:
        from transformers import BitsAndBytesConfig
        options["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
    _gpu.loaded[path, four_bit] = processor, AutoModelForImageTextToText.from_pretrained(path, **options).eval()
    return _gpu.loaded[path, four_bit]


def generate(path: Path, content: list[dict], max_new_tokens: int, four_bit: bool = False) -> str:
    """Answer one user message made of text, audio and image parts."""
    import torch

    with _gpu.lock:
        processor, model = _load(str(path), four_bit)
        inputs = processor.apply_chat_template(
            [{"role": "user", "content": content}], add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors="pt",
        ).to(model.device)
        if not four_bit:
            inputs = inputs.to(dtype=model.dtype)
        with torch.inference_mode():
            output = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        return processor.decode(output[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True)


def parse_json(text: str) -> dict:
    return json.loads(text[text.index("{"):text.rindex("}") + 1])
