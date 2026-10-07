"""Daily price history of the funds (Parquet): what the summary metrics of the catalog cannot tell.

With the real series of the chosen funds the app can see how they move together: it replaces a
fund that is almost a copy of another, splits by risk taking correlations into account, and
reports the volatility, worst fall and actual evolution of the portfolio as a whole.

Only the funds of one proposal are read (a few row groups, well under a second).
"""

import math
import os
from dataclasses import dataclass, replace
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from .models import Proposal, Recommendation
from .paths import ROOT
from .recommender import CUTOFF, allocation_limits, valid_allocation

TOO_SIMILAR = 0.95     # weekly-return correlation above which two funds count as the same bet
MIN_WEEKS = 26
SCENARIO_YEARS = 15     # past used to find the worst, median and best twelve months
FILE = "fondos_diarios.parquet"


def path() -> Path | None:
    for candidate in (os.getenv("DAILY_PARQUET"), ROOT / FILE, ROOT / "data/private" / FILE, ROOT.parent / "datos" / FILE):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def available() -> bool:
    return path() is not None


@lru_cache(maxsize=1)
def _dataset(location: str):
    import pyarrow.dataset as ds
    return ds.dataset(location, format="parquet")


def weekly_prices(isins: list[str], years: int):
    """Weekly closing prices (one column per fund) over the last `years` up to the catalog cutoff."""
    import pandas as pd
    import pyarrow.compute as pc

    start = CUTOFF - timedelta(days=round(365.25 * years) + 7)
    table = _dataset(str(path())).to_table(
        columns=["isin", "date", "adjusted_close", "close"],
        filter=pc.field("isin").isin(list(isins)) & (pc.field("date") >= start) & (pc.field("date") <= CUTOFF))
    frame = table.to_pandas()
    if frame.empty:
        return pd.DataFrame()
    frame["price"] = frame["adjusted_close"].where(frame["adjusted_close"] > 0, frame["close"])
    frame = frame[frame["price"] > 0]
    frame["date"] = pd.to_datetime(frame["date"])
    wide = frame.pivot_table(index="date", columns="isin", values="price", aggfunc="last").sort_index()
    return wide.resample("W-FRI").last().ffill(limit=2)


def _returns(isins: list[str], years: int):
    """Weekly returns on the dates all the funds share, or None when the history is too short."""
    prices = weekly_prices(isins, years)
    if any(isin not in prices.columns for isin in isins):
        return None, None
    prices = prices[list(isins)].dropna()
    returns = prices.pct_change(fill_method=None).dropna()
    if len(returns) < MIN_WEEKS:
        return None, None
    return prices, returns


@dataclass(frozen=True)
class Analysis:
    weeks: int
    volatility: float            # annualised, of the whole portfolio
    max_drawdown: float          # worst fall from a previous high, as a negative fraction
    total_return: float
    mean_correlation: float | None
    points: tuple[tuple[float, float], ...]   # (years since start, value of 1 invested)
    # Twelve-month returns of the portfolio over all the history its funds share
    worst_year: float | None = None
    median_year: float | None = None
    best_year: float | None = None
    year_windows: int = 0


def analyse(items, weights, years: int) -> Analysis | None:
    """How the proposed portfolio actually behaved, bought at the start and held."""
    if not available() or not items:
        return None
    isins = [item.fund.isin for item in items]
    long_prices, _ = _returns(isins, max(years, SCENARIO_YEARS))
    if long_prices is None:
        return None
    whole = (long_prices / long_prices.iloc[0]).mul(list(weights), axis=1).sum(axis=1)
    yearly = whole.pct_change(52, fill_method=None).dropna()
    scenarios = ((float(yearly.min()), float(yearly.median()), float(yearly.max()), len(yearly))
                 if len(yearly) >= MIN_WEEKS else (None, None, None, 0))
    # The evolution and the risk figures refer to the client's horizon (or what there is of it).
    start = long_prices.index[-1] - timedelta(days=round(365.25 * years))
    prices = long_prices[long_prices.index >= start]
    returns = prices.pct_change(fill_method=None).dropna()
    if len(returns) < MIN_WEEKS:
        return None
    value = (prices / prices.iloc[0]).mul(list(weights), axis=1).sum(axis=1)
    weekly = value.pct_change(fill_method=None).dropna()
    correlation = returns.corr().to_numpy()
    count = len(isins)
    pairs = [correlation[i][j] for i in range(count) for j in range(i + 1, count)]
    span = (value.index - value.index[0]).days / 365.25
    step = max(1, len(value) // 120)
    return Analysis(
        weeks=len(returns),
        volatility=float(weekly.std() * math.sqrt(52)),
        max_drawdown=float((value / value.cummax() - 1).min()),
        total_return=float(value.iloc[-1] - 1),
        mean_correlation=float(sum(pairs) / len(pairs)) if pairs else None,
        points=tuple((float(span[index]), float(value.iloc[index])) for index in range(0, len(value), step)),
        worst_year=scenarios[0], median_year=scenarios[1], best_year=scenarios[2], year_windows=scenarios[3],
    )


# Largest fall a client of each risk level is assumed to sit through; beyond it the fund loses score.
TOLERATED_FALL = {"bajo": 0.10, "medio": 0.25, "alto": 0.45}
SAME_BET = 0.90      # weekly-return correlation above which two candidates count as one idea


def inform(candidates: list[Recommendation], preferences, prices=None) -> list[Recommendation]:
    """Add to each candidate what its daily history says, and let it count in the ranking.

    Each fund gets its worst fall and worst twelve months over the horizon, and a group number
    shared by the candidates that move almost together. A fall deeper than the client's risk
    level tolerates (less if they said they would sell) lowers the score. Candidates without
    history are left as they were. The result is sorted best first again.

    `prices` are weekly prices already read (see `weekly_prices`); funds missing from them are
    left without history instead of being read again.
    """
    if not available() or not candidates:
        return candidates
    if prices is None:
        prices = weekly_prices([item.fund.isin for item in candidates], preferences.horizon_years)
    if prices.empty:
        return candidates
    known = [item.fund.isin for item in candidates if item.fund.isin in prices.columns]
    prices = prices[known]
    enough = prices.count() >= MIN_WEEKS
    correlation = prices.pct_change(fill_method=None).corr(min_periods=MIN_WEEKS).to_numpy()
    column = {isin: position for position, isin in enumerate(known)}
    falls = (prices / prices.cummax() - 1).min()
    worst = prices.pct_change(52, fill_method=None).min() if len(prices) > 52 + MIN_WEEKS else None
    tolerated = TOLERATED_FALL[preferences.risk] * (0.7 if preferences.loss_reaction == "vende" else 1.0)

    leaders: list[int] = []      # column of one fund per group, in ranking order
    informed = []
    for item in candidates:
        isin = item.fund.isin
        if isin not in column or not enough[isin]:
            informed.append(item)
            continue
        position = column[isin]
        close = (correlation[position, leaders] > SAME_BET).nonzero()[0] if leaders else ()
        if len(close):
            group = int(close[0]) + 1
        else:
            leaders.append(position)
            group = len(leaders)
        fall = float(falls[isin])
        year = float(worst[isin]) if worst is not None and worst[isin] == worst[isin] else None
        excess = max(0.0, abs(fall) - tolerated)
        note = f" En el periodo, su mayor caída fue del {abs(fall) * 100:.1f} %".replace(".", ",")
        note += (", más de lo que encaja con tu perfil." if excess > 0 else ".")
        informed.append(replace(item, score=item.score - 0.5 * excess, rationale=item.rationale + note,
                                drawdown=fall, worst_year=year, group=group))
    informed.sort(key=lambda item: (-item.score, item.fund.isin))
    return informed


def _bounded(raw: list[float]) -> list[float] | None:
    """Scale positive raw weights into the shared allocation limits, keeping their proportions."""
    lower, upper = allocation_limits(len(raw))
    low, high = 0.0, 1.0 / min(raw)
    for _ in range(80):
        scale = (low + high) / 2
        if sum(min(upper, max(lower, scale * value)) for value in raw) < 1:
            low = scale
        else:
            high = scale
    weights = [min(upper, max(lower, high * value)) for value in raw]
    return weights if valid_allocation(weights, len(raw)) else None


def risk_parity(items, years: int) -> list[float] | None:
    """Weights that make every fund contribute the same risk, using their real co-movement."""
    if not available() or len(items) < 2:
        return None
    _, returns = _returns([item.fund.isin for item in items], years)
    if returns is None:
        return None
    covariance = returns.cov().to_numpy() * 52
    count = len(items)
    weights = [1.0 / max(math.sqrt(covariance[i][i]), 1e-4) for i in range(count)]
    total = sum(weights)
    weights = [weight / total for weight in weights]
    for _ in range(300):
        marginal = [sum(covariance[i][j] * weights[j] for j in range(count)) for i in range(count)]
        contribution = [weights[i] * marginal[i] for i in range(count)]
        if min(contribution) <= 0:
            return None    # a strongly negative correlation: equal risk is not defined this way
        mean = sum(contribution) / count
        weights = [weights[i] * math.sqrt(mean / contribution[i]) for i in range(count)]
        total = sum(weights)
        weights = [weight / total for weight in weights]
    return _bounded(weights)


def decorrelate(chosen: list[Recommendation], pool: list[Recommendation], years: int) -> tuple[list[Recommendation], int]:
    """Replace a fund that moves almost exactly like a better-placed one with the next candidate."""
    if not available() or len(chosen) < 2:
        return chosen, 0
    spare = [item for item in pool if item not in chosen][:25]
    isins = [item.fund.isin for item in chosen + spare]
    prices = weekly_prices(isins, years)
    returns = prices.pct_change(fill_method=None)

    def similar(first: str, second: str) -> bool:
        if first not in returns.columns or second not in returns.columns:
            return False
        pair = returns[[first, second]].dropna()
        return len(pair) >= MIN_WEEKS and pair[first].corr(pair[second]) > TOO_SIMILAR

    kept, swaps = [], 0
    for item in chosen:
        if not any(similar(item.fund.isin, other.fund.isin) for other in kept):
            kept.append(item)
            continue
        substitute = next((candidate for candidate in spare if candidate not in kept
                           and not any(similar(candidate.fund.isin, other.fund.isin) for other in kept)), None)
        if substitute is None:
            kept.append(item)       # nothing better to offer: keep the model's choice
        else:
            spare.remove(substitute)
            kept.append(substitute)
            swaps += 1
    return kept, swaps


def refine(proposal: Proposal, pool: list[Recommendation], years: int) -> Proposal:
    """Second look at a proposal with the daily history. Any failure leaves it as it was."""
    if not available():
        return proposal
    try:
        items, swaps = decorrelate(list(proposal.items), pool, years)
        by_rules = proposal.method.startswith("Reglas")
        weights = list(proposal.weights)
        note = ""
        if swaps or by_rules:
            parity = risk_parity(items, years)
            if parity:
                weights, note = parity, "reparto por paridad de riesgo con correlaciones reales"
            elif swaps:
                return proposal     # cannot weight the new set reliably
        if swaps:
            note = (f"{swaps} {'fondo sustituido' if swaps == 1 else 'fondos sustituidos'} por moverse casi igual que otro"
                    + (f"; {note}" if note else ""))
        if not note:
            return proposal
        return replace(proposal, items=tuple(items), weights=tuple(weights),
                       method=f"{proposal.method}; con el histórico diario: {note}")
    except Exception:
        return proposal
