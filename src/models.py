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
    asset_class: str | None = None
    diversification: str | None = None
    objective: str | None = None
    experience: str | None = None
    loss_reaction: str | None = None
    fund_count: int | None = None
    amount_needs_clarification: bool = False


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
    # From the fund's own documents (DFI/KID, ficha, folleto), when they have been processed
    sri: int | None = None            # indicador resumido de riesgo oficial, 1-7
    costs: float | None = None        # costes corrientes anuales, en %
    min_investment: float | None = None
    min_currency: str = ""
    brochure: str = ""                # fuente del documento

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


@dataclass(frozen=True)
class Criteria:
    """Search criteria decided by the model and applied by code to the whole catalog."""
    weights: tuple[float, float, float]  # ajuste al riesgo, Sharpe, rentabilidad
    target_vol: float
    min_annual_return: float | None = None
    keywords: tuple[str, ...] = ()
    explanation: str = ""

    def describe(self) -> str:
        fit, sharpe, ret = (round(weight * 100) for weight in self.weights)
        text = (f"peso del ajuste al riesgo {fit} %, del Sharpe {sharpe} % y de la rentabilidad {ret} %; "
                f"volatilidad objetivo {self.target_vol:.0%}")
        if self.min_annual_return is not None:
            text += f"; rentabilidad anual mínima {self.min_annual_return:.0%}"
        if self.keywords:
            text += f"; nombre del fondo con alguna de estas palabras: {', '.join(self.keywords)}"
        return text


@dataclass(frozen=True)
class Proposal:
    items: tuple[Recommendation, ...]
    weights: tuple[float, ...]
    method: str
    comment: str = ""
