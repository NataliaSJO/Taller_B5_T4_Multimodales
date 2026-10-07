"""Evidence-aware, reproducible shortlist. Never invents fund holdings."""

import math
import re
from dataclasses import replace
from datetime import date

from .models import Criteria, Fund, Preferences, Recommendation
from .preferences import normalize

CUTOFF = date(2026, 10, 5)
# Score weights (ajuste al riesgo, Sharpe, rentabilidad) according to the stated objective.
WEIGHTS = {
    None: (0.55, 0.25, 0.20),
    "crecimiento": (0.40, 0.25, 0.35),
    "preservación": (0.65, 0.25, 0.10),
    "rentas": (0.60, 0.30, 0.10),
}
RISK = {
    "bajo": (0.06, 0.10),
    "medio": (0.13, 0.20),
    "alto": (0.24, 0.35),
}
# Most catalog rows have no verified exposure, so the fund name is the fallback evidence.
NAME_HINTS = {value: re.compile(rf"\b(?:{pattern})") for value, pattern in {
    "global": r"global|world|mundial|internacional|international",
    "europa": r"europ|eurozone|euroland|iberia|nordic",
    "estados unidos": r"us\b|usa\b|america|s&p|nasdaq|north america",
    "asia": r"asia|japan|japon|china|india|pacific",
    "emergentes": r"emerging|emergente|frontier",
    "tecnología": r"tech|tecnolog|digital|robot|semiconductor|artificial intelligence",
    "salud": r"health|salud|biotech|pharma|medical",
    "energía": r"energy|energia|oil|renewable|solar|clean",
    "finanzas": r"financ|bank|insurance",
    "renta fija": r"bond|bono|renta fija|fixed income|credit|treasury|deuda|debt",
    "renta variable": r"equit|acciones|renta variable|stock",
    "mixto": r"mixed|mixto|balanced|multi.?asset|allocation",
    "monetario": r"money market|monetario|liquidity|cash",
}.items()}


# The catalog has no subscription minimums. Every fund is considered; only the choice between share
# classes of one fund depends on the amount: a retail class is preferred under RETAIL_BELOW.
RETAIL_BELOW = 100_000.0
INSTITUTIONAL = re.compile(r"\b(?:institutional|institucional|inst|instl|ia)\b"
                           r"|\b(?:class|clase|cl)\s+[ixzs]\b|\bi[- ](?:acc|dist|eur|usd|cap)\b")

# Words that distinguish share classes of one fund, not different portfolios.
CLASS_WORDS = frozenset((
    "fund funds fondo fi fcp sicav ucits class clase retail institutional inst investor acc accumulation "
    "dist distribution capitalisation cap inc eur usd gbp gbx chf nok sek the and"
).split())


def _family_name(name: str) -> str:
    """Best-effort grouping of share classes of the same fund; never merges source records."""
    clean = re.sub(r"\s+in\s+[a-z]{2}\W*$", "", normalize(name))
    clean = re.sub(r"\bs\s*&\s*p\b", "sp", clean)
    words = re.sub(r"[^a-z0-9 ]+", " ", clean).split()
    kept = [word for word in words if word not in CLASS_WORDS]
    # Strip only likely suffix class codes; retain index numbers, hedge status
    # and short geographic/strategy terms. Unknown classes can remain separate.
    class_suffixes = {"ia", "ib", "ic", "id", "ii"}
    while kept and ((len(kept[-1]) == 1 and kept[-1].isalpha()) or kept[-1] in class_suffixes):
        kept.pop()
    return " ".join(kept) or " ".join(words)


def _verified(value: str, source_url: str) -> bool:
    clean = normalize(value).strip()
    return bool(source_url and clean and clean not in {"—", "-", "n/a", "n/d"}
                and not clean.startswith(("pendiente", "sin dato", "no verificad", "no disponible", "desconocid")))


def _matches_region(fund: Fund, region: str) -> bool | None:
    if not _verified(fund.regions, fund.source_url):
        if (region == "global" and _verified(fund.strategy, fund.source_url)
                and any(term in normalize(fund.strategy) for term in ("global", "mundial", "msci world"))):
            return True
        return None
    haystack = normalize(fund.regions)
    if region == "global":
        return any(term in haystack for term in ("global", "mundial", "msci world"))
    aliases = {"estados unidos": ("estados unidos", "america", "americas", "eeuu", "usa"),
               "europa": ("europa", "zona euro"),
               "asia": ("asia", "japon"),
               "emergentes": ("emergente",)}
    return _verified(fund.regions, fund.source_url) and any(
        token in haystack for token in aliases.get(region, (region,))
    )


def _matches_sector(fund: Fund, sector: str) -> bool | None:
    if not _verified(fund.sectors, fund.source_url):
        return None
    haystack = normalize(fund.sectors)
    aliases = {"tecnología": ("tecnologia", "tech"),
               "salud": ("salud", "sanidad", "health"),
               "energía": ("energia", "energetic"),
               "finanzas": ("finanza", "financier", "banco")}
    return any(token in haystack for token in aliases.get(sector, (normalize(sector),)))


def _matches_asset(fund: Fund, asset_class: str) -> bool | None:
    if not _verified(fund.assets, fund.source_url):
        return None
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


def _thematic(fund: Fund, preferences: Preferences) -> list[str] | None:
    """Preferences met only by the fund name; None when one of them is not met at all."""
    by_name = []
    for value, verified in ((preferences.region, _matches_region), (preferences.sector, _matches_sector),
                            (preferences.asset_class, _matches_asset)):
        if not value:
            continue
        match = verified(fund, value)
        if match is True:
            continue
        if match is False:
            return None
        if not NAME_HINTS[value].search(normalize(fund.name)):
            return None
        by_name.append(value)
    return by_name


def recommend(funds: list[Fund], preferences: Preferences, limit: int = 5,
              criteria: Criteria | None = None) -> tuple[list[Recommendation], dict]:
    """Filter and score the whole catalog. `criteria` (decided by a model) tunes the search, but the
    hard constraints stay: currency, recent data and the volatility ceiling of the declared risk."""
    if preferences.horizon_years not in (1, 3, 5):
        raise ValueError("Elige un horizonte de 1, 3 o 5 años")
    if preferences.risk not in RISK:
        raise ValueError("Indica un nivel de riesgo bajo, medio o alto")
    if not preferences.currency:
        raise ValueError("Indica una moneda")
    if preferences.excluded_sectors:
        return [], {"reason": "El catálogo no verifica la composición completa de la cartera; no permite garantizar exclusiones sectoriales."}

    target_vol, max_vol = RISK[preferences.risk]
    fit_weight, sharpe_weight, return_weight = WEIGHTS[preferences.objective]
    wanted = None
    if criteria:
        target_vol = min(criteria.target_vol, max_vol)
        fit_weight, sharpe_weight, return_weight = criteria.weights
        if criteria.keywords:
            wanted = re.compile(r"\b(?:" + "|".join(re.escape(word) for word in criteria.keywords) + ")")
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
        by_name = _thematic(fund, preferences)
        if by_name is None:
            continue
        annual_return = (1 + ret) ** (1 / preferences.horizon_years) - 1
        if criteria and criteria.min_annual_return is not None and annual_return < criteria.min_annual_return:
            continue
        if wanted and not wanted.search(normalize(f"{fund.name} {fund.strategy} {fund.assets} {fund.regions} {fund.sectors}")):
            continue
        counts["profile"] += 1

        risk_fit = max(0.0, 1.0 - abs(vol - target_vol) / max_vol)
        return_component = max(0.0, min(1.0, (annual_return + 0.10) / 0.30))
        sharpe_component = 0.25 if sharpe is None else max(0.0, min(1.0, (sharpe + 1) / 3))
        score = fit_weight * risk_fit + sharpe_weight * sharpe_component + return_weight * return_component
        ratio = "sin Sharpe verificable" if sharpe is None else f"Sharpe {sharpe:+.2f}"
        rationale = (f"Volatilidad histórica {vol:.1%} dentro del límite {max_vol:.0%} del perfil; "
                     f"rentabilidad acumulada {ret:+.1%} a {preferences.horizon_years} años; {ratio}.")
        if by_name:
            rationale += f" Encaja con {', '.join(by_name)} por el nombre del fondo; exposición no verificada."
        scored.append(Recommendation(fund=fund, score=score, rationale=rationale))
    scored.sort(key=lambda item: (-item.score, item.fund.isin))
    counts["eligible"] = len(scored)
    # One share class per fund: the best scored, or a retail one when the amount is small.
    retail = preferences.amount is not None and preferences.amount < RETAIL_BELOW
    families: dict[str, Recommendation] = {}
    for item in scored:
        family = _family_name(item.fund.name)
        current = families.get(family)
        if current is None:
            if len(families) >= limit:
                if not retail:
                    break
                continue
            families[family] = item
        elif retail and _institutional(current.fund) and not _institutional(item.fund):
            families[family] = item
    selected = [
        replace(item, rationale=item.rationale + " Parece una clase institucional: comprueba el mínimo de suscripción.")
        if retail and _institutional(item.fund) else item
        for item in families.values()
    ]
    return selected, counts


def _institutional(fund: Fund) -> bool:
    return bool(INSTITUTIONAL.search(normalize(fund.name)))


def allocation_limits(count: int) -> tuple[float, float]:
    if count < 1 or count > 20:
        raise ValueError("El reparto requiere entre 1 y 20 fondos")
    return (1.0, 1.0) if count == 1 else (0.05, 0.80 if count == 2 else 0.60)


def valid_allocation(weights, count: int) -> bool:
    if len(weights) != count or not count:
        return False
    lower, upper = allocation_limits(count)
    return (all(type(value) in (int, float) and math.isfinite(value)
                and lower - 1e-9 <= value <= upper + 1e-9 for value in weights)
            and math.isclose(sum(weights), 1.0, abs_tol=1e-9, rel_tol=0))


def allocate(items, years: int) -> list[float]:
    """Inverse-volatility allocation with the same bounds as model allocations."""
    lower, upper = allocation_limits(len(items))
    inverse = []
    for item in items:
        vol = item.fund.metrics(years)[1]
        if type(vol) not in (int, float) or not math.isfinite(vol) or vol < 0:
            raise ValueError("Volatilidad no válida para repartir la inversión")
        inverse.append(1.0 / max(vol, 0.01))
    # Find the scale for bounded proportional weights. This retains the original
    # inverse-volatility proportions whenever neither bound is active.
    low, high = 0.0, 1.0 / min(inverse)
    for _ in range(80):
        scale = (low + high) / 2
        if sum(min(upper, max(lower, scale * value)) for value in inverse) < 1:
            low = scale
        else:
            high = scale
    weights = [min(upper, max(lower, high * value)) for value in inverse]
    if not valid_allocation(weights, len(items)):
        raise ValueError("No se ha podido obtener un reparto válido")
    return weights
