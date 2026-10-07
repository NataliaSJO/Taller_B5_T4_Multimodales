"""Alternative version: one multimodal model (Gemma 3n) hears, understands, asks and selects.

It replaces Whisper, the extraction rules, the scripted questions and the Gemma 1B filter of the
specialised pipeline. It cannot speak, so the answer is still voiced by Piper, and the catalog is
still reduced by the hard constraints before the model sees it.
"""

from dataclasses import replace

from . import ai_filter, extraction
from .hf_model import generate, parse_json
from .models import Criteria, Preferences, Proposal, Recommendation
from .paths import OMNI_PATH
from .preferences import parse_heuristic
from .recommender import allocate

LABEL = "Gemma 3n E2B (modelo único)"
CANDIDATES = 150
FIELDS, INSTRUCTIONS = extraction.FIELDS, extraction.INSTRUCTIONS
_preferences = extraction.to_preferences


def available() -> bool:
    return (OMNI_PATH / "config.json").is_file()


def listen(audio: list[str] = (), images: list[str] = ()) -> str:
    """What the client says in the attached audio (and any text shown in attached images)."""
    ask = "Transcribe exactamente lo que dice el audio, en español. Devuelve solo la transcripción."
    if images:
        ask = ("Transcribe en español lo que dice el audio, si lo hay, y el texto que aparece en la imagen. "
               "Devuelve solo esa transcripción.")
    content = ([{"type": "audio", "audio": path} for path in audio]
               + [{"type": "image", "image": path} for path in images] + [{"type": "text", "text": ask}])
    return " ".join(generate(OMNI_PATH, content, 200).split())


def understand(history: list[tuple[str, str]], known: Preferences, text: str = "",
               audio: list[str] = (), images: list[str] = ()) -> tuple[Preferences, str, str]:
    """One turn: what the client said, what it adds to the profile and the next question.

    The same model first listens and then reasons over the transcript; asked to do both at once
    with the conversation in the prompt, it repeats the adviser's words instead of the audio.
    """
    heard = listen(audio, images) if audio or images else ""
    said = " ".join(part for part in (heard, text) if part)
    answer = parse_json(generate(OMNI_PATH, [{"type": "text", "text": extraction.prompt(history, known, said)}], 400))
    new, ask = extraction.read(answer)
    # An explicit exclusion in the transcript must survive a model omission.
    excluded = tuple(dict.fromkeys(new.excluded_sectors + parse_heuristic(said).excluded_sectors))
    new = replace(new, excluded_sectors=excluded,
                  sector=None if new.sector in excluded else new.sector)
    return new, said, ask


def decide(preferences: Preferences, conversation: str) -> Criteria | None:
    """Search criteria for the whole catalog, decided by the multimodal model."""
    try:
        prompt = ai_filter.criteria_prompt(preferences, conversation)
        return ai_filter.criteria_from(parse_json(generate(OMNI_PATH, [{"type": "text", "text": prompt}], 300)), preferences)
    except Exception:
        return None


def select(candidates: list[Recommendation], preferences: Preferences, conversation: str) -> Proposal:
    """Same task and validation as the specialised filter, answered by the multimodal model."""
    years = preferences.horizon_years
    count = min(ai_filter.requested_count(preferences), len(candidates))
    fallback = tuple(candidates[:count])
    if len(candidates) <= count:
        return Proposal(fallback, tuple(allocate(fallback, years)), "Reglas deterministas")
    pool = candidates[:max(CANDIDATES, count + 3)]
    try:
        prompt = ai_filter._prompt(pool, preferences, conversation, count)
        answer = parse_json(generate(OMNI_PATH, [{"type": "text", "text": prompt}], 300))
        chosen, shares, comment = ai_filter._validated(answer, pool, preferences, count)
    except Exception as exc:  # any model failure must not block the proposal
        return Proposal(fallback, tuple(allocate(fallback, years)),
                        f"Reglas deterministas ({LABEL} no disponible: {type(exc).__name__})")
    return Proposal(tuple(chosen), tuple(shares), f"{LABEL} + validación local", comment)
