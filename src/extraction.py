"""Understand one turn of the client with a language model: profile data and next question."""

from .conversation import HORIZONS
from .models import Preferences
from .preferences import ASSET_CLASSES, REGIONS, SECTORS

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


def to_preferences(data: dict) -> Preferences:
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


def prompt(history: list[tuple[str, str]], known: Preferences, said: str) -> str:
    known_text = ", ".join(f"{field}={value}" for field, value in vars(known).items() if value) or "ninguno"
    lines = "\n".join(f"{'Cliente' if role == 'user' else 'Asesor'}: {line}" for role, line in history)
    return INSTRUCTIONS.format(history=lines or "(empieza ahora)", known=known_text, last=f"«{said}»")


def read(answer: dict) -> tuple[Preferences, str]:
    """Validated preferences and the model's next question (empty when it should not be used)."""
    new = to_preferences(answer)
    ask = " ".join(str(answer.get("pregunta") or "").split())
    if new.horizon_years is not None and new.horizon_years not in HORIZONS:
        ask = ""  # the page explains that only 1, 3 and 5 years have data
    return new, ask
