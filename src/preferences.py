"""Extract explicit investment preferences from Spanish natural language."""

import re
import unicodedata

from .models import Preferences

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
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in text if not unicodedata.combining(char))


def _amount(text: str) -> float | None:
    match = re.search(r"(?<![\w,])([\d.,\s]+?)\s*(?:€|euros?\b)", text)
    if not match:
        return None
    value = match.group(1).strip().replace(" ", "")
    if "." in value and "," in value:
        value = value.replace(".", "").replace(",", ".")
    elif "." in value and re.fullmatch(r"\d{1,3}(?:\.\d{3})+", value):
        value = value.replace(".", "")
    else:
        value = value.replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return None


def parse_heuristic(text: str) -> Preferences:
    clean = normalize(text)
    year_match = re.search(r"\b(\d{1,2}|un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+an(?:o|os)\b", clean)
    horizon = None
    if year_match:
        raw = year_match.group(1)
        horizon = int(raw) if raw.isdigit() else WORDS[raw]
    risk = None
    if re.search(r"\b(conservador|prudente|riesgo bajo|bajo riesgo|poco riesgo|sin riesgo|no quiero sustos|tranquil[oa])\b", clean):
        risk = "bajo"
    elif re.search(r"\b(agresivo|arriesgado|riesgo alto|alto riesgo|mucho riesgo|bastante riesgo)\b", clean):
        risk = "alto"
    elif re.search(r"\b(moderado|equilibrado|riesgo medio|riesgo moderado)\b", clean):
        risk = "medio"
    currency = None
    if re.search(r"€|\beur\b|\beuros?\b", clean):
        currency = "EUR"
    elif re.search(r"\busd\b|\bdolares?\b", clean):
        currency = "USD"
    elif re.search(r"\bgbp\b|\blibras?\b", clean):
        currency = "GBP"
    elif re.search(r"\bchf\b|\bfrancos? suizos?\b", clean):
        currency = "CHF"
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
                       amount=_amount(clean), region=region, sector=sector,
                       excluded_sectors=tuple(excluded), asset_class=asset_class)
