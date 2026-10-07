"""Alternative version: one multimodal model (Gemma 3n) hears, understands, asks and selects.

It replaces Whisper, the extraction rules, the scripted questions and the Gemma 1B filter of the
specialised pipeline. It cannot speak, so the answer is still voiced by Piper, and the catalog is
still reduced by the hard constraints before the model sees it.
"""

from . import ai_filter
from .conversation import HORIZONS
from .hf_model import generate, parse_json
from .models import Criteria, Preferences, Proposal, Recommendation
from .paths import OMNI_PATH
from .preferences import ASSET_CLASSES, REGIONS, SECTORS
from .recommender import allocate

LABEL = "Gemma 3n E2B (modelo único)"
CANDIDATES = 150
# JSON key -> (Preferences field, accepted values)
FIELDS = {
    "riesgo": ("risk", ("bajo", "medio", "alto")),
    "zona": ("region", tuple(REGIONS)),
    "sector": ("sector", tuple(SECTORS)),
    "clase_activo": ("asset_class", tuple(ASSET_CLASSES)),
    "diversificacion": ("diversification", ("baja", "media", "alta")),
    "objetivo": ("objective", ("crecimiento", "preservación", "rentas")),
    "experiencia": ("experience", ("baja", "alta")),
    "ante_caidas": ("loss_reaction", ("vende", "espera", "compra")),
}
INSTRUCTIONS = """Eres un asesor financiero que conversa con un cliente para recomendarle fondos de inversión.

Conversación hasta ahora:
{history}

Datos ya conocidos del cliente: {known}

El último mensaje del cliente es {last}. Devuelve solo un objeto JSON con estas claves:
- plazo_anios: años que quiere mantener la inversión, como número, o null.
- riesgo: "bajo", "medio", "alto" o null.
- divisa: código de tres letras de la moneda que mencione (euros es "EUR", dólares es "USD", libras es "GBP"), o null.
- importe: cantidad a invertir como número, o null.
- zona: "global", "europa", "estados unidos", "asia", "emergentes" o null.
- sector: "tecnología", "salud", "energía", "finanzas" o null.
- clase_activo: "renta fija", "renta variable", "mixto", "monetario" o null.
- diversificacion: "baja", "media", "alta" o null.
- objetivo: "crecimiento", "preservación", "rentas" o null.
- experiencia: "baja" si no ha invertido antes, "alta" si ya ha invertido, o null.
- ante_caidas: qué haría si su inversión cae mucho: "vende", "espera", "compra" o null.
- pregunta: lo siguiente que le dices al cliente, tuteándole. Si aún no sabes el plazo, el riesgo o la divisa, pregúntale por lo que falte. Si ya los sabes, pregúntale por su objetivo, su experiencia y qué haría ante una caída fuerte. Si ya lo sabes todo, deja una cadena vacía.

Usa null para todo lo que el cliente no haya dicho. No inventes datos."""


def available() -> bool:
    return (OMNI_PATH / "config.json").is_file()


def _preferences(data: dict) -> Preferences:
    """Keep only values of the expected type and vocabulary; anything else counts as not said."""
    values = {}
    for key, (field, allowed) in FIELDS.items():
        value = data.get(key)
        if isinstance(value, str) and value.strip().lower() in allowed:
            values[field] = value.strip().lower()
    years, amount, currency = data.get("plazo_anios"), data.get("importe"), data.get("divisa")
    if isinstance(years, (int, float)) and 1 <= years <= 50:
        values["horizon_years"] = int(years)
    if isinstance(amount, (int, float)) and 0 < amount < 1_000_000_000:
        values["amount"] = float(amount)
    if isinstance(currency, str) and len(currency.strip()) == 3 and currency.strip().isalpha():
        values["currency"] = currency.strip().upper()
    return Preferences(**values)


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
    known_text = ", ".join(f"{field}={value}" for field, value in vars(known).items() if value) or "ninguno"
    prompt = INSTRUCTIONS.format(
        history="\n".join(f"{'Cliente' if role == 'user' else 'Asesor'}: {line}" for role, line in history) or "(empieza ahora)",
        known=known_text, last=f"«{said}»",
    )
    data = parse_json(generate(OMNI_PATH, [{"type": "text", "text": prompt}], 400))
    ask = " ".join(str(data.get("pregunta") or "").split())
    new = _preferences(data)
    if new.horizon_years is not None and new.horizon_years not in HORIZONS:
        ask = ""  # the page explains that only 1, 3 and 5 years have data
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
    count = min(ai_filter.FUNDS[preferences.diversification], len(candidates))
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
