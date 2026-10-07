"""Fund documents (DFI/KID, fichas, folletos) preprocessed by scripts/procesar_folletos.py."""

import csv
from dataclasses import dataclass, replace
from pathlib import Path

from .models import Fund, Preferences
from .recommender import MAX_SRI


@dataclass(frozen=True)
class Brochure:
    isin: str
    name: str
    source: str
    in_catalog: bool
    sri: int | None
    period: int | None
    costs: float | None
    minimum: float | None
    currency: str
    category: str
    assets: str
    regions: str
    sectors: str
    objective: str
    url: str


def _number(value: str, kind=float):
    return kind(float(value)) if value else None


def load(path: Path) -> dict[str, Brochure]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return {row["isin"]: Brochure(
            isin=row["isin"], name=row["nombre"], source=row["fuente"], in_catalog=row["en_catalogo"] != "no",
            sri=_number(row["sri"], int), period=_number(row["periodo_anios"], int), costs=_number(row["costes_pct"]),
            minimum=_number(row["inversion_minima"]), currency=row["divisa"], category=row["categoria"],
            assets=row["activos"], regions=row["regiones"], sectors=row["sectores"],
            objective=row["objetivo"], url=row["url"],
        ) for row in csv.DictReader(handle)}


def enrich(funds: list[Fund], brochures: dict[str, Brochure]) -> list[Fund]:
    """Add what each fund's documents say. Exposures read there count as verified."""
    enriched = []
    for fund in funds:
        doc = brochures.get(fund.isin)
        if doc is None:
            enriched.append(fund)
            continue
        enriched.append(replace(
            fund, sri=doc.sri, costs=doc.costs, min_investment=doc.minimum, min_currency=doc.currency,
            brochure=doc.source, strategy=fund.strategy or doc.category or doc.objective[:160],
            assets=fund.assets or doc.assets, regions=fund.regions or doc.regions,
            sectors=fund.sectors or doc.sectors, source_url=fund.source_url or doc.url or "folleto",
        ))
    return enriched


def without_history(brochures: dict[str, Brochure], preferences: Preferences, limit: int = 5) -> list[Brochure]:
    """Funds known only from their documents that fit the profile.

    They have no price history in the catalog, so they cannot be scored or weighted; they are
    listed apart, filtered by official risk class, currency and stated preferences.
    """
    ceiling = MAX_SRI[preferences.risk]
    fits = []
    for doc in brochures.values():
        if doc.in_catalog or doc.sri is None or doc.sri > ceiling:
            continue
        currency = doc.currency or ("EUR" if doc.isin.startswith("ES") else "")
        if currency != preferences.currency:
            continue
        if preferences.amount and doc.minimum and doc.minimum > preferences.amount:
            continue
        if any(wanted and wanted not in stated for wanted, stated in (
                (preferences.region, doc.regions), (preferences.sector, doc.sectors),
                (preferences.asset_class, doc.assets))):
            continue
        fits.append(doc)
    fits.sort(key=lambda doc: (ceiling - doc.sri, doc.costs if doc.costs is not None else 9.0, doc.isin))
    return fits[:limit]
