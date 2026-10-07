"""Extract explicit investment preferences from Spanish natural language."""

import re
import unicodedata

from .models import Preferences
from .money import parse_money

REGIONS = {
    "global": ("global", "globales", "mundial", "mundiales", "mundo"),
    "europa": ("europa", "europeo", "europeos", "europea", "europeas"),
    "estados unidos": ("estados unidos", "eeuu", "usa", "norteamerica", "norteamericano"),
    "asia": ("asia", "asiatico", "asiaticos", "asiatica", "asiaticas"),
    "emergentes": ("emergentes", "emergente"),
}
SECTORS = {
    "tecnología": ("tecnologia", "tecnologico", "tecnologicos", "tecnologica", "tecnologicas", "tech"),
    "salud": ("salud", "sanidad", "healthcare"),
    "energía": ("energia", "energetico", "energeticos", "energetica", "energeticas"),
    "finanzas": ("finanzas", "financiero", "financieros", "financiera", "financieras", "bancos"),
}
ASSET_CLASSES = {
    "renta fija": ("renta fija", "bonos", "deuda"),
    "renta variable": ("renta variable", "acciones"),
    "mixto": ("mixto", "mixta", "mixtos", "mixtas"),
    "monetario": ("monetario", "monetarios", "liquidez"),
}
DIVERSIFICATION = {
    "baja": r"\b(un solo fondo|un unico fondo|pocos fondos|concentrad[oa]s?|sin diversificar|poco diversificad[oa])\b",
    "alta": r"\b(muy diversificad[oa]s?|mucha diversificacion|maxima diversificacion|diversificar (?:mucho|al maximo)|muchos fondos|bien repartid[oa])\b",
    "media": r"\b(diversificad[oa]s?|diversificar|diversificacion|repartid[oa]|varios fondos)\b",
}
WORDS = {"un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
         "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower()).replace("−", "-")
    return "".join(char for char in text if not unicodedata.combining(char))


RISK_OPTIONS = (
    ("bajo", r"\b(conservador|prudente|riesgo bajo|bajo riesgo|poco riesgo|sin riesgo|no quiero sustos|tranquil[oa])\b"),
    ("alto", r"\b(agresivo|arriesgado|riesgo alto|alto riesgo|mucho riesgo|bastante riesgo)\b"),
    ("medio", r"\b(moderado|equilibrado|riesgo medio|riesgo moderado)\b"),
)
BARE_RISK_OPTIONS = (
    ("bajo", r"\b(bajo|baja|poco)\b"),
    ("alto", r"\b(alto|alta|mucho)\b"),
    ("medio", r"\b(medio|media|intermedio)\b"),
)


def explicit_choice(text: str, options) -> tuple[bool, str | None]:
    """Recognise affirmed choices; ambiguous or only negated mentions have no value.

    Longest matches protect phrases such as «no he invertido» from the nested
    «he invertido». Negation applies within a clause, and explicit corrections
    («mejor», «prefiero», «sino») replace earlier choices.
    """
    clean = normalize(text)
    matches = sorted(((match.start(), match.end(), value)
                      for value, pattern in options for match in re.finditer(pattern, clean)),
                     key=lambda item: (item[0], -item[1]))
    accepted, end = [], -1
    for start, stop, value in matches:
        if start < end:
            continue
        end = stop
        # «y riesgo alto» can still belong to a negated list. Reset the scope
        # only when the conjunction introduces a new statement or condition.
        boundary = (r"[,.!?;]|\b(?:pero|sino|aunque|prefiero|mejor)\b"
                    r"|\by\b(?=\s+(?:yo|si|quiero|prefiero|no|nunca|tengo|he)\b)")
        boundaries = [match.end() for match in re.finditer(boundary, clean) if match.end() <= start]
        prefix = clean[boundaries[-1] if boundaries else 0:start]
        if not re.search(r"\b(no|nunca|jamas|ni|sin|evitar|evito|excluir)\b", prefix):
            accepted.append((start, value))
    corrections = list(re.finditer(r"\b(?:mejor|prefiero|sino)\b", clean))
    if corrections:
        corrected = [(pos, value) for pos, value in accepted if pos >= corrections[-1].end()]
        if corrected:
            accepted = corrected
    values = {value for _, value in accepted}
    return bool(matches), next(iter(values)) if len(values) == 1 else None


def risk_choice(text: str, bare: bool = False) -> tuple[bool, str | None]:
    clean = normalize(text)
    if bare or re.search(r"\briesgo\b", clean):
        clean = re.sub(r"\b(prefiero|mejor|sino)\s+(bajo|medio|alto)\b", r"\1 riesgo \2", clean)
    return explicit_choice(clean, RISK_OPTIONS + (BARE_RISK_OPTIONS if bare else ()))


def _amount(text: str) -> float | None:
    return parse_money(text)[1]


def requested_funds(text: str) -> int | None:
    options = [(str(count), rf"\b(?:{count}|{word})\s+fondos?\b")
               for word, count in WORDS.items() if 2 <= count <= 7]
    options.append(("1", r"\b(?:un (?:solo|unico) fondo|(?:solo|solamente) un fondo|1 fondo)\b"))
    _, count = explicit_choice(text, options)
    return int(count) if count is not None else None


def parse_heuristic(text: str) -> Preferences:
    clean = normalize(text)
    year_match = re.search(r"\b(\d{1,2}|un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+an(?:o|os)\b", clean)
    horizon = None
    if year_match:
        raw = year_match.group(1)
        horizon = int(raw) if raw.isdigit() else WORDS[raw]
    _, risk = risk_choice(clean)
    currency = None
    if re.search(r"€|\beur\b|\beuros?\b", clean):
        currency = "EUR"
    elif re.search(r"\busd\b|\bdolar(?:es)?\b", clean):
        currency = "USD"
    elif re.search(r"\bgbp\b|\blibras?\b", clean):
        currency = "GBP"
    elif re.search(r"\bchf\b|\bfrancos? suizos?\b", clean):
        currency = "CHF"
    mentioned_amount, amount, amount_currency = parse_money(clean)
    currency = amount_currency or currency
    excluded = []
    for sector, words in SECTORS.items():
        if any(re.search(rf"\b(?:sin|evitar|excluir|excluye|no quiero)\s+(?:fondos?\s+de\s+)?{re.escape(word)}\b", clean) for word in words):
            excluded.append(sector)
    sector = next((sector for sector, words in SECTORS.items()
                   if sector not in excluded and any(re.search(rf"\b{re.escape(word)}\b", clean) for word in words)), None)
    region = next((region for region, words in REGIONS.items()
                   if any(re.search(rf"\b{re.escape(word)}\b", clean) for word in words)), None)
    asset_matches = {kind for kind, words in ASSET_CLASSES.items()
                     if any(re.search(rf"\b{re.escape(word)}\b", clean) for word in words)}
    asset_class = ("mixto" if {"renta fija", "renta variable"}.issubset(asset_matches)
                   else next(iter(asset_matches)) if len(asset_matches) == 1 else None)
    diversification = next((level for level, pattern in DIVERSIFICATION.items() if re.search(pattern, clean)), None)
    return Preferences(horizon_years=horizon, risk=risk, currency=currency, diversification=diversification,
                       amount=amount, region=region, sector=sector,
                       excluded_sectors=tuple(excluded), asset_class=asset_class,
                       fund_count=requested_funds(clean),
                       amount_needs_clarification=mentioned_amount and amount is None)
