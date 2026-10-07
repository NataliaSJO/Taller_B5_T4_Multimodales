"""Extract explicit investment preferences from Spanish natural language."""

import os
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
    if re.search(r"\b(conservador|prudente|riesgo bajo|bajo riesgo)\b", clean):
        risk = "bajo"
    elif re.search(r"\b(agresivo|arriesgado|riesgo alto|alto riesgo)\b", clean):
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
    return Preferences(horizon_years=horizon, risk=risk, currency=currency,
                       amount=_amount(clean), region=region, sector=sector,
                       excluded_sectors=tuple(excluded), asset_class=asset_class)


def parse_with_optional_llm(text: str, use_llm: bool = False) -> tuple[Preferences, str]:
    base = parse_heuristic(text)
    router_key = os.getenv("OPENROUTER_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    if not use_llm or not (router_key or openai_key):
        return base, "Reglas locales"
    try:
        from openai import OpenAI
        from pydantic import BaseModel, ConfigDict

        class Extracted(BaseModel):
            model_config = ConfigDict(extra="forbid")

            horizon_years: int | None
            risk: str | None
            currency: str | None
            amount: float | None
            region: str | None
            sector: str | None
            excluded_sectors: list[str]
            asset_class: str | None

        messages = [
            {"role": "system", "content": "Extrae únicamente preferencias explícitas del texto en español. No infieras edad, ingresos, situación patrimonial ni tolerancia al riesgo. Usa null si falta un dato. Riesgo: bajo, medio o alto. Moneda ISO. Clase de activo: renta fija, renta variable, mixto o monetario. No recomiendes productos."},
            {"role": "user", "content": text[:4000]},
        ]
        if router_key:
            model = os.getenv("OPENROUTER_MODEL", "openai/gpt-6-luna")
            client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=router_key,
                            timeout=20.0, max_retries=1)
            extra_body = {"provider": {"require_parameters": True}}
            if model.startswith("openai/gpt-6-luna"):
                extra_body["reasoning"] = {"effort": "none"}
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_schema", "json_schema": {
                    "name": "fund_preferences", "strict": True,
                    "schema": Extracted.model_json_schema(),
                }},
                extra_body=extra_body,
            )
            parsed = Extracted.model_validate_json(response.choices[0].message.content)
            method = f"OpenRouter ({model}) + validación local"
        else:
            client = OpenAI(api_key=openai_key, timeout=20.0, max_retries=1)
            response = client.responses.parse(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                input=messages,
                text_format=Extracted,
            )
            parsed = response.output_parsed
            method = "OpenAI + validación local"
        if parsed is None:
            return base, "Reglas locales (respuesta del modelo no utilizable)"
        risk = parsed.risk if parsed.risk in ("bajo", "medio", "alto") else None
        currency = parsed.currency.upper() if parsed.currency and re.fullmatch(r"[A-Za-z]{3}", parsed.currency) else None
        horizon = parsed.horizon_years if parsed.horizon_years and 1 <= parsed.horizon_years <= 50 else None
        amount = parsed.amount if parsed.amount and 0 < parsed.amount < 1_000_000_000 else None
        extracted = Preferences(
            horizon_years=horizon or base.horizon_years,
            risk=risk or base.risk,
            currency=currency or base.currency,
            amount=amount or base.amount,
            region=parsed.region or base.region,
            sector=parsed.sector or base.sector,
            excluded_sectors=tuple(parsed.excluded_sectors or base.excluded_sectors),
            asset_class=parsed.asset_class if parsed.asset_class in ASSET_CLASSES else base.asset_class,
        )
        return extracted, method
    except Exception:
        provider = "OpenRouter" if router_key else "OpenAI"
        return base, f"Reglas locales ({provider} no disponible)"
