"""Turn-by-turn dialogue: accumulate preferences and ask for what is still missing."""

import re
from dataclasses import replace

from .models import MAX_HORIZON, WINDOWS, Preferences, metric_years
from .money import format_money, parse_money
from .preferences import WORDS, explicit_choice, normalize, parse_heuristic, requested_funds, risk_choice

HORIZONS = WINDOWS  # windows with catalog metrics; any horizon up to MAX_HORIZON is accepted


def valid_horizon(years) -> bool:
    return type(years) is int and 1 <= years <= MAX_HORIZON

REQUIRED = ("horizon_years", "risk", "currency")
THEMATIC = ("region", "sector", "asset_class")
# What an adviser would also ask. Optional: asked once, never required.
EXTRA = {
    "objective": (
        "qué buscas sobre todo: hacer crecer el dinero, conservarlo u obtener rentas",
        (("preservación", r"\b(conservar|preservar|proteger|no perder|mantener el valor|seguridad)"),
         ("rentas", r"\b(rentas|ingresos|dividendos|cobrar)\b"),  # plural: «renta fija» is not an objective
         ("crecimiento", r"\b(crecer|crecimiento|maximizar|revalorizar|ganar mas|rentabilidad alta)")),
    ),
    "experience": (
        "si has invertido antes en fondos",
        (("baja", r"\b(nunca he invertido|no he invertido|primera vez|sin experiencia|no tengo experiencia|poca experiencia|principiante|novat[oa])"),
         ("alta", r"\b(he invertido|ya invierto|invierto desde|tengo experiencia|con experiencia|llevo anos|expert[oa])")),
    ),
    "loss_reaction": (
        "qué harías si tu inversión cayera un veinte por ciento en un año: vender, esperar o comprar más",
        (("vende", r"\b(vend\w+|saldria|retiraria|sacaria)\b"),
         ("compra", r"\b(compraria|comprar mas|aprovecharia|invertiria mas|aportaria mas)\b"),
         ("espera", r"\b(esperaria|esperar|aguantaria|mantendria|no haria nada)\b")),
    ),
}
LOWER_RISK = {"alto": "medio", "medio": "bajo"}
QUESTIONS = {
    "horizon_years": "durante cuántos años quieres mantener la inversión",
    "risk": "qué nivel de riesgo aceptas: bajo, medio o alto",
    "currency": "en qué divisa quieres invertir, por ejemplo euros o dólares",
    "amount": "un importe positivo inferior a mil millones, con un máximo de dos decimales",
}
CURRENCY_NAMES = {"EUR": "euros", "USD": "dólares", "GBP": "libras", "CHF": "francos suizos"}
GREETING = ("Hola, soy FondoClaro. Cuéntame, escribiendo o hablando, cuánto quieres invertir, "
            "durante cuántos años, con qué nivel de riesgo y en qué divisa. Si quieres, dime también "
            "un sector, una zona geográfica o cuánto quieres diversificar.")


def parse_turn(text: str, pending: tuple[str, ...] = ()) -> Preferences:
    """Parse one user turn; bare answers such as «cinco» or «medio» count if we asked for them."""
    parsed = parse_heuristic(text)
    clean = normalize(text)
    if "amount" in pending:
        mentioned, amount, currency = parse_money(clean, allow_bare=True)
        if mentioned:
            parsed = replace(parsed, amount=amount, currency=currency or parsed.currency,
                             amount_needs_clarification=amount is None)
    if "horizon_years" in pending and parsed.horizon_years is None:
        match = re.search(r"(?<![\d.,])(\d{1,2})(?![.,]?\d)|\b(uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\b", clean)
        if match:
            parsed = replace(parsed, horizon_years=int(match.group(1)) if match.group(1) else WORDS[match.group(2)])
    if "risk" in pending and parsed.risk is None:
        _, risk = risk_choice(clean, bare=True)
        parsed = replace(parsed, risk=risk)
    for field, (_, options) in EXTRA.items():
        _, value = explicit_choice(clean, options)
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
        amount=None if new.amount_needs_clarification else new.amount if new.amount is not None else profile.amount,
        region=new.region or profile.region,
        sector=new.sector or profile.sector,
        excluded_sectors=excluded,
        asset_class=new.asset_class or profile.asset_class,
        diversification=new.diversification or profile.diversification,
        objective=new.objective or profile.objective,
        experience=new.experience or profile.experience,
        loss_reaction=new.loss_reaction or profile.loss_reaction,
        fund_count=(new.fund_count if new.fund_count is not None else
                    None if new.diversification is not None else profile.fund_count),
        amount_needs_clarification=(new.amount_needs_clarification or
                                   (new.amount is None and profile.amount_needs_clarification)),
    )


def missing(profile: Preferences) -> tuple[str, ...]:
    return tuple(field for field in REQUIRED
                 if (not valid_horizon(profile.horizon_years) if field == "horizon_years"
                     else not getattr(profile, field))) + (("amount",) if profile.amount_needs_clarification else ())


def describe(profile: Preferences) -> str:
    parts = []
    if profile.amount is not None:
        parts.append(f"{format_money(profile.amount)} {CURRENCY_NAMES.get(profile.currency, profile.currency or '')}".strip())
    elif profile.currency:
        parts.append(CURRENCY_NAMES.get(profile.currency, profile.currency))
    if valid_horizon(profile.horizon_years):
        parts.append(f"{profile.horizon_years} {'año' if profile.horizon_years == 1 else 'años'}")
    if profile.risk:
        parts.append(f"riesgo {profile.risk}")
    parts.extend(value for value in (profile.region, profile.sector, profile.asset_class) if value)
    if profile.diversification:
        parts.append(f"diversificación {profile.diversification}")
    if profile.fund_count:
        parts.append(f"{profile.fund_count} {'fondo' if profile.fund_count == 1 else 'fondos'}")
    return ", ".join(parts)


def question(profile: Preferences) -> str:
    """Spoken question for the required fields that are still missing."""
    fields = missing(profile)
    understood = describe(profile)
    text = f"De momento he entendido: {understood}. " if understood else ""
    if profile.horizon_years is not None and not valid_horizon(profile.horizon_years):
        text += f"Has dicho {profile.horizon_years} años, pero necesito un plazo entre 1 y {MAX_HORIZON} años. "
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
    if valid_horizon(profile.horizon_years) and profile.horizon_years not in WINDOWS:
        window = metric_years(profile.horizon_years)
        notes.append(f"Para comparar fondos uso sus cifras a {window} {'año' if window == 1 else 'años'}, la ventana "
                     f"del catálogo más cercana a tus {profile.horizon_years} años.")
    if profile.objective == "rentas":
        notes.append("El catálogo no informa de repartos de dividendos, así que he priorizado la estabilidad.")
    return replace(profile, risk=risk), notes


def wants_more(text: str) -> bool | None:
    """Answer to «¿quieres el detalle?»: True, False, or None when the client is talking about something else."""
    clean = normalize(text).strip(" .!¿?¡,")
    words = clean.split()
    if re.search(r"\b(detall\w*|cuenta\w*|explica\w*|mas informacion|mas info|quiero saber|dime)\b", clean):
        return not re.search(r"^no\b|\bno hace falta\b|\bno quiero\b", clean)
    if len(words) <= 6 and re.search(r"^(si|vale|claro|venga|adelante|ok|okey|por favor|de acuerdo|perfecto)\b", clean):
        return True
    if len(words) <= 8 and re.search(r"^(no|nada mas|asi esta bien|es suficiente|con eso (?:me )?basta|gracias)\b", clean):
        return False
    return None


def is_yes(text: str) -> bool:
    return relaxation_answer(text) is True


def relaxation_answer(text: str) -> bool | None:
    """Only an unambiguous assent can remove a pending restriction."""
    clean = normalize(text).strip(" .!¿?¡")
    if re.search(r"\b(no|nunca|jamas|tampoco|manten\w*|conserv\w*|dejalo|dejala)\b", clean):
        return False
    if re.search(r"\b(?:con|respetando)\s+(?:la |las |esa |esas )?(?:exclusion\w*|restriccion\w*|preferencia\w*|filtro\w*)", clean):
        return False
    # Match complete utterances, not a keyword hidden in a conditional or a new request.
    assent = r"(?:si|vale|de acuerdo|adelante|ok|okey|claro|continua|quitalo|quitala|quitalos|quitalas|hazlo)"
    removal = r"(?:(?:sigue|continua) sin (?:ella|ellas|el|ellos|esa exclusion|ese filtro)|quita (?:esa exclusion|ese filtro))"
    if re.fullmatch(rf"(?:{assent}|{removal})(?:[\s,;]+(?:{assent}|{removal}))*(?:,? por favor)?", clean):
        return True
    return None


def apply_turn(profile: Preferences, new: Preferences, text: str,
               pending: tuple[str, ...] = (), pending_relax: tuple[str, ...] = ()):
    """Shared dialogue transition for both pages, including explicit denials.

    Return the profile, any still-pending relaxation, and a reply when selection
    must stop. A rejected or ambiguous restriction change never triggers a proposal.
    """
    updated = merge(profile, new)
    mentioned, amount, currency = parse_money(normalize(text), allow_bare="amount" in pending)
    if mentioned:
        updated = replace(updated, amount=amount, currency=currency or updated.currency,
                          amount_needs_clarification=amount is None)
    count = requested_funds(text)
    if count is not None:
        updated = replace(updated, fund_count=count)
    mentioned, risk = risk_choice(text, bare="risk" in pending)
    if mentioned:
        updated = replace(updated, risk=risk)
    for field, (_, options) in EXTRA.items():
        mentioned, value = explicit_choice(text, options)
        if mentioned:
            updated = replace(updated, **{field: value})
    if pending_relax:
        answer = relaxation_answer(text)
        if answer is True:
            return relax(updated, pending_relax), (), ""
        if answer is False:
            return updated, (), ("Mantengo tus restricciones. Con los datos actuales no puedo generar "
                                 "una propuesta que las cumpla. Puedes cambiar tus preferencias.")
        return updated, pending_relax, ("Mantengo tus restricciones. ¿Quieres retirarlas para continuar? "
                                        "Responde «sí, quítalas» o «no, mantenlas».")
    return updated, (), ""


def relax(profile: Preferences, fields: tuple[str, ...]) -> Preferences:
    return replace(profile, **{field: () if field == "excluded_sectors" else None for field in fields})
