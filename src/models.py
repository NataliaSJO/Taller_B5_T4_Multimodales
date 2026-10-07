from dataclasses import dataclass

WINDOWS = (1, 3, 5)     # years for which the catalog has return, volatility and Sharpe
MAX_HORIZON = 30


def metric_years(years: int) -> int:
    """Catalog window used to compare funds for a horizon: the longest one that fits in it."""
    return max((window for window in WINDOWS if window <= years), default=WINDOWS[0])


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
        """Return, volatility and Sharpe over the catalog window that corresponds to `years`."""
        if type(years) is not int or not 1 <= years <= MAX_HORIZON:
            raise ValueError(f"El horizonte debe estar entre 1 y {MAX_HORIZON} años")
        window = metric_years(years)
        return (getattr(self, f"return_{window}y"),
                getattr(self, f"vol_{window}y"),
                getattr(self, f"sharpe_{window}y"))


@dataclass(frozen=True)
class Recommendation:
    fund: Fund
    score: float
    rationale: str
    # From the daily price history, when it is available
    drawdown: float | None = None     # worst fall from a high over the horizon, negative
    worst_year: float | None = None   # worst twelve months over the horizon
    group: int | None = None          # funds with the same number move almost together


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
