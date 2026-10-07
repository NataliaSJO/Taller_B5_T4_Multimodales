"""Evidence-aware, reproducible shortlist. Never invents fund holdings."""

import re
from datetime import date

from .models import Fund, Preferences, Recommendation
from .preferences import normalize

CUTOFF = date(2026, 10, 5)
RISK = {
    "bajo": (0.06, 0.10),
    "medio": (0.13, 0.20),
    "alto": (0.24, 0.35),
}


def _family_name(name: str) -> str:
    """Best-effort grouping of obvious share classes; never merges source records."""
    value = normalize(name)
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"\s+(?:class|clase|cl)\s+[a-z0-9]+(?:\s+(?:acc|dist))?$", "", value)
    value = re.sub(r"\s+[a-z0-9]{1,2}\s+in\s+[a-z]{2,3}$", "", value)
    value = re.sub(r"\s+[a-z]\s+(?:fi|fund|sicav|ucits)$", "", value)
    value = re.sub(r"\s+[a-z]$", "", value)
    return value


def _verified(value: str, source_url: str) -> bool:
    return bool(source_url and value and not value.lower().startswith("pendiente"))


def _matches_region(fund: Fund, region: str) -> bool:
    if not fund.source_url:
        return False
    haystack = normalize(f"{fund.regions} {fund.strategy}")
    if region == "global":
        return any(term in haystack for term in ("global", "mundial", "msci world"))
    aliases = {"estados unidos": ("estados unidos", "america", "americas", "eeuu", "usa"),
               "europa": ("europa", "zona euro"),
               "asia": ("asia", "japon"),
               "emergentes": ("emergente",)}
    return _verified(fund.regions, fund.source_url) and any(
        token in haystack for token in aliases.get(region, (region,))
    )


def _matches_sector(fund: Fund, sector: str) -> bool:
    if not _verified(fund.sectors, fund.source_url):
        return False
    haystack = normalize(fund.sectors)
    aliases = {"tecnología": ("tecnologia", "tech"),
               "salud": ("salud", "sanidad", "health"),
               "energía": ("energia", "energetic"),
               "finanzas": ("finanza", "financier", "banco")}
    return any(token in haystack for token in aliases.get(sector, (normalize(sector),)))


def _matches_asset(fund: Fund, asset_class: str) -> bool:
    if not _verified(fund.assets, fund.source_url):
        return False
    assets = normalize(fund.assets)
    fixed = "renta fija" in assets or "bonos" in assets or "deuda" in assets
    equity = "renta variable" in assets or "acciones" in assets
    mixed = "mixto" in assets or "mixta" in assets or (fixed and equity)
    if asset_class == "renta fija":
        return fixed and not equity and not mixed
    if asset_class == "renta variable":
        return equity and not fixed and not mixed
    if asset_class == "mixto":
        return mixed
    if asset_class == "monetario":
        return "monetario" in assets or "liquidez" in assets
    return False


def recommend(funds: list[Fund], preferences: Preferences, limit: int = 5) -> tuple[list[Recommendation], dict]:
    if preferences.horizon_years not in (1, 3, 5):
        raise ValueError("Elige un horizonte de 1, 3 o 5 años")
    if preferences.risk not in RISK:
        raise ValueError("Indica un nivel de riesgo bajo, medio o alto")
    if not preferences.currency:
        raise ValueError("Indica una moneda")
    if preferences.excluded_sectors:
        return [], {"reason": "El catálogo no verifica la composición completa de la cartera; no permite garantizar exclusiones sectoriales."}

    target_vol, max_vol = RISK[preferences.risk]
    counts = {"catalog": len(funds), "currency": 0, "metrics": 0, "risk": 0, "profile": 0}
    scored = []
    for fund in funds:
        # GBX denotes pence sterling; its percentage returns are comparable with GBP.
        if fund.currency != preferences.currency and not (preferences.currency == "GBP" and fund.currency == "GBX"):
            continue
        counts["currency"] += 1
        ret, vol, sharpe = fund.metrics(preferences.horizon_years)
        if ret is None or vol is None or not (-0.99 < ret <= 3.0 and 0 <= vol <= 1.0):
            continue
        try:
            last = date.fromisoformat(fund.last_date)
        except ValueError:
            continue
        if not (0 <= (CUTOFF - last).days <= 30):
            continue
        counts["metrics"] += 1
        if vol > max_vol:
            continue
        counts["risk"] += 1
        if preferences.region and not _matches_region(fund, preferences.region):
            continue
        if preferences.sector and not _matches_sector(fund, preferences.sector):
            continue
        if preferences.asset_class and not _matches_asset(fund, preferences.asset_class):
            continue
        counts["profile"] += 1

        annual_return = (1 + ret) ** (1 / preferences.horizon_years) - 1
        risk_fit = max(0.0, 1.0 - abs(vol - target_vol) / max_vol)
        return_component = max(0.0, min(1.0, (annual_return + 0.10) / 0.30))
        sharpe_component = 0.25 if sharpe is None else max(0.0, min(1.0, (sharpe + 1) / 3))
        score = 0.55 * risk_fit + 0.25 * sharpe_component + 0.20 * return_component
        ratio = "sin Sharpe verificable" if sharpe is None else f"Sharpe {sharpe:+.2f}"
        rationale = (f"Volatilidad histórica {vol:.1%} dentro del límite {max_vol:.0%} del perfil; "
                     f"rentabilidad acumulada {ret:+.1%} a {preferences.horizon_years} años; {ratio}.")
        scored.append(Recommendation(fund=fund, score=score, rationale=rationale))
    scored.sort(key=lambda item: (-item.score, item.fund.isin))
    counts["eligible"] = len(scored)
    selected = []
    families = set()
    for item in scored:
        family = _family_name(item.fund.name)
        if family in families:
            continue
        selected.append(item)
        families.add(family)
        if len(selected) >= limit:
            break
    return selected, counts
