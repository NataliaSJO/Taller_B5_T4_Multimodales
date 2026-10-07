"""Evidence-aware, reproducible shortlist. Never invents fund holdings."""

import re
from dataclasses import replace
from datetime import date

from .models import Criteria, Fund, Preferences, Recommendation
from .preferences import normalize

CUTOFF = date(2026, 10, 5)
# Highest official risk class (SRI, 1-7) accepted for each declared risk. The classes follow
# volatility bands (3: up to 12 %, 4: up to 20 %, 6: up to 80 %), in line with the limits below.
MAX_SRI = {"bajo": 3, "medio": 4, "alto": 6}
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
    "dist distribution capitalisation cap inc hedged unhedged eur usd gbp gbx chf nok sek the and"
).split())


def _family_name(name: str) -> str:
    """Best-effort grouping of share classes of the same fund; never merges source records."""
    words = re.sub(r"[^a-z0-9 ]+", " ", normalize(name)).split()
    kept = [word for word in words if len(word) > 2 and word not in CLASS_WORDS and not word.isdigit()]
    return " ".join(kept) or " ".join(words)


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


def _thematic(fund: Fund, preferences: Preferences) -> list[str] | None:
    """Preferences met only by the fund name; None when one of them is not met at all."""
    by_name = []
    for value, verified in ((preferences.region, _matches_region), (preferences.sector, _matches_sector),
                            (preferences.asset_class, _matches_asset)):
        if not value or verified(fund, value):
            continue
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
    counts = {"catalog": len(funds), "currency": 0, "metrics": 0, "risk": 0, "profile": 0,
              "sri": 0, "minimum": 0}
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
        if fund.sri is not None and fund.sri > MAX_SRI[preferences.risk]:
            counts["sri"] += 1          # the official risk class says no, whatever the past volatility
            continue
        if not _affordable(fund, preferences):
            counts["minimum"] += 1
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
        if fund.costs is not None:
            score -= min(fund.costs, 3.0) * 0.02   # each point of yearly costs weighs on the choice
        ratio = "sin Sharpe verificable" if sharpe is None else f"Sharpe {sharpe:+.2f}"
        rationale = (f"Volatilidad histórica {vol:.1%} dentro del límite {max_vol:.0%} del perfil; "
                     f"rentabilidad acumulada {ret:+.1%} a {preferences.horizon_years} años; {ratio}.")
        if fund.brochure:
            facts = [f"riesgo oficial {fund.sri} de 7" if fund.sri else "",
                     f"costes corrientes {fund.costs:.2f} %".replace(".", ",") if fund.costs is not None else "",
                     f"inversión mínima {fund.min_investment:,.0f} {fund.min_currency}".replace(",", ".")
                     if fund.min_investment else ""]
            if any(facts):
                rationale += f" Según su documentación ({fund.brochure}): {'; '.join(fact for fact in facts if fact)}."
        if by_name:
            rationale += f" Encaja con {', '.join(by_name)} por el nombre del fondo; exposición no verificada."
        scored.append(Recommendation(fund=fund, score=score, rationale=rationale))
    scored.sort(key=lambda item: (-item.score, item.fund.isin))
    counts["eligible"] = len(scored)
    # One share class per fund: the best scored, or a retail one when the amount is small.
    retail = preferences.amount is not None and preferences.amount < RETAIL_BELOW
    looks_institutional = lambda fund: fund.min_investment is None and _institutional(fund)  # a known minimum decides
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
        elif retail and looks_institutional(current.fund) and not looks_institutional(item.fund):
            families[family] = item
    selected = [
        replace(item, rationale=item.rationale + " Parece una clase institucional: comprueba el mínimo de suscripción.")
        if retail and looks_institutional(item.fund) else item
        for item in families.values()
    ]
    return selected, counts


def _affordable(fund: Fund, preferences: Preferences) -> bool:
    """False when the documented minimum investment clearly exceeds what the client wants to invest."""
    if not preferences.amount or not fund.min_investment:
        return True
    same = fund.min_currency == preferences.currency
    return fund.min_investment <= preferences.amount * (1.0 if same else 1.5)  # margin for another currency


def _institutional(fund: Fund) -> bool:
    return bool(INSTITUTIONAL.search(normalize(fund.name)))


def allocate(items, years: int | None = None) -> list[float]:
    """Fallback split when no model proposes one: more weight to the funds that fit the profile
    best (their score), with no fund above 40 % when there are three or more.

    Not a portfolio optimisation: correlations between funds are not available.
    """
    scores = [max(item.score, 0.01) for item in items]
    weights = [score / sum(scores) for score in scores]
    cap = 0.40 if len(items) >= 3 else 1.0
    for _ in range(len(items)):
        over = [index for index, weight in enumerate(weights) if weight > cap + 1e-9]
        if not over:
            break
        excess = sum(weights[index] - cap for index in over)
        free = [index for index, weight in enumerate(weights) if weight < cap - 1e-9]
        room = sum(weights[index] for index in free)
        for index in over:
            weights[index] = cap
        for index in free:
            weights[index] += excess * weights[index] / room
    return weights
