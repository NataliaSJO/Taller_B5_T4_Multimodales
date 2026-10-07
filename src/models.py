from dataclasses import dataclass


@dataclass(frozen=True)
class Preferences:
    horizon_years: int | None = None
    risk: str | None = None
    currency: str | None = None
    amount: float | None = None
    region: str | None = None
    sector: str | None = None
    excluded_sectors: tuple[str, ...] = ()


@dataclass(frozen=True)
class Fund:
    isin: str
    name: str
    currency: str
    provider_type: str
    strategy: str
    assets: str
    regions: str
    sectors: str
    source_url: str
    last_date: str
    return_1y: float | None
    vol_1y: float | None
    sharpe_1y: float | None
    return_3y: float | None
    vol_3y: float | None
    sharpe_3y: float | None
    return_5y: float | None
    vol_5y: float | None
    sharpe_5y: float | None

    def metrics(self, years: int) -> tuple[float | None, float | None, float | None]:
        if years not in (1, 3, 5):
            raise ValueError("Solo se admiten horizontes de 1, 3 y 5 años")
        return (getattr(self, f"return_{years}y"),
                getattr(self, f"vol_{years}y"),
                getattr(self, f"sharpe_{years}y"))


@dataclass(frozen=True)
class Recommendation:
    fund: Fund
    score: float
    rationale: str
