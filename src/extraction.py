"""Understand one turn of the client with a language model: profile data and next question."""

from .conversation import valid_horizon
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
- sectores_excluidos: lista de sectores que el cliente quiere evitar, usando "tecnología", "salud", "energía" o "finanzas". Lista vacía si no menciona exclusiones. Nunca conviertas una exclusión en una preferencia de inclusión.
- clase_activo: "renta fija", "renta variable", "mixto", "monetario" o null.
- diversificacion: "baja", "media", "alta" o null.
- numero_fondos: número entero entre 1 y 7 si el cliente pide una cantidad concreta; «un solo fondo» significa 1. Si no lo dice, null.
- objetivo: "crecimiento", "preservación", "rentas" o null.
- experiencia: "baja" si no ha invertido antes, "alta" si ya ha invertido, o null.
- ante_caidas: qué haría si su inversión cae mucho: "vende", "espera", "compra" o null.
- pregunta: lo siguiente que le dices al cliente, tuteándole. Si aún no sabes el plazo, el riesgo o la divisa, pregúntale por lo que falte. Si ya los sabes, pregúntale por su objetivo, su experiencia y qué haría ante una caída fuerte. Si ya lo sabes todo, deja una cadena vacía.

Respeta las negaciones y las correcciones: «no quiero riesgo alto, prefiero medio» significa riesgo medio.
Usa null para los campos escalares que el cliente no haya dicho. No inventes datos."""


def to_preferences(data: dict) -> Preferences:
    """Keep only values of the expected type and vocabulary; anything else counts as not said."""
    values = {}
    excluded = data.get("sectores_excluidos", [])
    if excluded is None:
        excluded = []
    if not isinstance(excluded, list) or any(
        not isinstance(value, str) or value.strip().lower() not in SECTORS for value in excluded
    ):
        raise ValueError("Sectores excluidos no válidos")
    values["excluded_sectors"] = tuple(dict.fromkeys(value.strip().lower() for value in excluded))
    for key, (field, allowed) in FIELDS.items():
        value = data.get(key)
        if isinstance(value, str) and value.strip().lower() in allowed:
            values[field] = value.strip().lower()
    years, amount, currency = data.get("plazo_anios"), data.get("importe"), data.get("divisa")
    count = data.get("numero_fondos")
    if type(count) is int and 1 <= count <= 7:
        values["fund_count"] = count
    if type(years) in (int, float) and 1 <= years <= 50 and int(years) == years:
        values["horizon_years"] = int(years)
    if type(amount) in (int, float) and 0.01 <= amount < 1_000_000_000 and round(amount, 2) == amount:
        values["amount"] = float(amount)
    elif amount is not None:
        values["amount_needs_clarification"] = True
    if isinstance(currency, str) and len(currency.strip()) == 3 and currency.strip().isalpha():
        values["currency"] = currency.strip().upper()
    if values.get("sector") in values["excluded_sectors"]:
        values["sector"] = None
    return Preferences(**values)


def prompt(history: list[tuple[str, str]], known: Preferences, said: str) -> str:
    known_text = ", ".join(f"{field}={value}" for field, value in vars(known).items() if value) or "ninguno"
    lines = "\n".join(f"{'Cliente' if role == 'user' else 'Asesor'}: {line}" for role, line in history)
    return INSTRUCTIONS.format(history=lines or "(empieza ahora)", known=known_text, last=f"«{said}»")


def read(answer: dict) -> tuple[Preferences, str]:
    """Validated preferences and the model's next question (empty when it should not be used)."""
    new = to_preferences(answer)
    ask = " ".join(str(answer.get("pregunta") or "").split())
    if new.horizon_years is not None and not valid_horizon(new.horizon_years):
        ask = ""  # the page explains which horizons are accepted
    return new, ask
