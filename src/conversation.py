"""Turn-by-turn dialogue: accumulate preferences and ask for what is still missing."""

import re
from dataclasses import replace

from .models import Preferences
from .preferences import WORDS, normalize, parse_heuristic

HORIZONS = (1, 3, 5)
REQUIRED = ("horizon_years", "risk", "currency")
THEMATIC = ("region", "sector", "asset_class")
# What an adviser would also ask. Optional: asked once, never required.
EXTRA = {
    "objective": (
        "qué buscas sobre todo: hacer crecer el dinero, conservarlo u obtener rentas",
        (("preservación", r"\b(conservar|preservar|proteger|no perder|mantener el valor|seguridad)"),
         ("rentas", r"\b(rentas?|ingresos|dividendos|cobrar)\b"),
         ("crecimiento", r"\b(crecer|crecimiento|maximizar|revalorizar|ganar mas|rentabilidad alta)")),
    ),
    "experience": (
        "si has invertido antes en fondos",
        (("baja", r"\b(nunca he invertido|no he invertido|primera vez|sin experiencia|no tengo experiencia|poca experiencia|principiante|novat[oa])"),
         ("alta", r"\b(he invertido|ya invierto|invierto desde|tengo experiencia|con experiencia|llevo anos|expert[oa])")),
    ),
    "loss_reaction": (
        "qué harías si tu inversión cayera un veinte por ciento en un año: vender, esperar o comprar más",
        (("vende", r"\b(vender\w*|vendo|saldria|retiraria|sacaria)\b"),
         ("compra", r"\b(compraria|comprar mas|aprovecharia|invertiria mas|aportaria mas)\b"),
         ("espera", r"\b(esperaria|esperar|aguantaria|mantendria|no haria nada)\b")),
    ),
}
LOWER_RISK = {"alto": "medio", "medio": "bajo"}
QUESTIONS = {
    "horizon_years": "durante cuántos años quieres mantener la inversión: uno, tres o cinco",
    "risk": "qué nivel de riesgo aceptas: bajo, medio o alto",
    "currency": "en qué divisa quieres invertir, por ejemplo euros o dólares",
}
CURRENCY_NAMES = {"EUR": "euros", "USD": "dólares", "GBP": "libras", "CHF": "francos suizos"}
GREETING = ("Hola, soy FondoClaro. Cuéntame, escribiendo o hablando, cuánto quieres invertir, "
            "durante cuántos años, con qué nivel de riesgo y en qué divisa. Si quieres, dime también "
            "un sector, una zona geográfica o cuánto quieres diversificar.")


def parse_turn(text: str, pending: tuple[str, ...] = ()) -> Preferences:
    """Parse one user turn; bare answers such as «cinco» or «medio» count if we asked for them."""
    parsed = parse_heuristic(text)
    clean = normalize(text)
    if "horizon_years" in pending and parsed.horizon_years is None:
        match = re.search(r"(?<![\d.,])(\d{1,2})(?![.,]?\d)|\b(uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\b", clean)
        if match:
            parsed = replace(parsed, horizon_years=int(match.group(1)) if match.group(1) else WORDS[match.group(2)])
    if "risk" in pending and parsed.risk is None:
        for risk, pattern in (("bajo", r"\b(bajo|baja|poco)\b"), ("alto", r"\b(alto|alta|mucho)\b"),
                              ("medio", r"\b(medio|media|intermedio)\b")):
            if re.search(pattern, clean):
                parsed = replace(parsed, risk=risk)
                break
    for field, (_, options) in EXTRA.items():
        value = next((value for value, pattern in options if re.search(pattern, clean)), None)
        if value:
            parsed = replace(parsed, **{field: value})
    return parsed


def merge(profile: Preferences, new: Preferences) -> Preferences:
    """Later turns override earlier ones; exclusions accumulate."""
    excluded = tuple(dict.fromkeys(profile.excluded_sectors + new.excluded_sectors))
    return Preferences(
        horizon_years=new.horizon_years if new.horizon_years is not None else profile.horizon_years,
        risk=new.risk or profile.risk,
        currency=new.currency or profile.currency,
        amount=new.amount if new.amount is not None else profile.amount,
        region=new.region or profile.region,
        sector=new.sector or profile.sector,
        excluded_sectors=excluded,
        asset_class=new.asset_class or profile.asset_class,
        diversification=new.diversification or profile.diversification,
        objective=new.objective or profile.objective,
        experience=new.experience or profile.experience,
        loss_reaction=new.loss_reaction or profile.loss_reaction,
    )


def missing(profile: Preferences) -> tuple[str, ...]:
    return tuple(field for field in REQUIRED
                 if (profile.horizon_years not in HORIZONS if field == "horizon_years"
                     else not getattr(profile, field)))


def describe(profile: Preferences) -> str:
    parts = []
    if profile.amount is not None:
        parts.append(f"{profile.amount:.0f} {CURRENCY_NAMES.get(profile.currency, profile.currency or '')}".strip())
    elif profile.currency:
        parts.append(CURRENCY_NAMES.get(profile.currency, profile.currency))
    if profile.horizon_years in HORIZONS:
        parts.append(f"{profile.horizon_years} {'año' if profile.horizon_years == 1 else 'años'}")
    if profile.risk:
        parts.append(f"riesgo {profile.risk}")
    parts.extend(value for value in (profile.region, profile.sector, profile.asset_class) if value)
    if profile.diversification:
        parts.append(f"diversificación {profile.diversification}")
    return ", ".join(parts)


def question(profile: Preferences) -> str:
    """Spoken question for the required fields that are still missing."""
    fields = missing(profile)
    understood = describe(profile)
    text = f"De momento he entendido: {understood}. " if understood else ""
    if profile.horizon_years is not None and profile.horizon_years not in HORIZONS:
        text += (f"Has dicho {profile.horizon_years} años, pero solo tengo datos históricos "
                 "a uno, tres o cinco años. ")
    asks = [QUESTIONS[field] for field in fields]
    return text + "Para recomendarte fondos necesito saber " + " y ".join(asks) + "."


def extra_question(profile: Preferences) -> str | None:
    """One optional follow-up with what an adviser would still want to know."""
    asks = [ask for field, (ask, _) in EXTRA.items() if not getattr(profile, field)]
    if not asks:
        return None
    return ("Ya tengo lo imprescindible. Para afinar como lo haría un asesor, cuéntame "
            + "; ".join(asks) + ". Si prefieres no contestar, di «continúa».")


def advise(profile: Preferences) -> tuple[Preferences, list[str]]:
    """Suitability check: lower the declared risk when the answers do not support it."""
    notes = []
    risk = profile.risk
    if profile.loss_reaction == "vende" and risk in LOWER_RISK:
        notes.append(f"Como dices que venderías ante una caída fuerte, he bajado el riesgo de {risk} a {LOWER_RISK[risk]}.")
        risk = LOWER_RISK[risk]
    if profile.experience == "baja" and risk == "alto":
        notes.append("Como es tu primera experiencia con fondos, he bajado el riesgo de alto a medio.")
        risk = "medio"
    if profile.objective == "rentas":
        notes.append("El catálogo no informa de repartos de dividendos, así que he priorizado la estabilidad.")
    return replace(profile, risk=risk), notes


def is_yes(text: str) -> bool:
    return bool(re.search(r"\b(si|vale|de acuerdo|adelante|ok|okey|claro|continua|quitalo|quitala|hazlo)\b", normalize(text)))


def relax(profile: Preferences, fields: tuple[str, ...]) -> Preferences:
    return replace(profile, **{field: () if field == "excluded_sectors" else None for field in fields})
