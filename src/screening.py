"""Evaluate many funds without making the client wait: start while the conversation goes on.

Three ideas work together:

* Start early. As soon as horizon, risk and currency are known, a background thread decides the
  search criteria, filters the catalog and reads the daily history, while the page is still
  asking the adviser's questions.
* One line per group. Funds that move almost together count as one idea; the model sees the
  best fund of each group, so a list of 150 lines stands for several times as many funds.
* Batches while talking. With what time is left, the model makes a first cut of the following
  groups, batch by batch; its picks are promoted into the final list.

Nothing here touches the page: the thread works on plain data and the page collects it.
"""

import threading
from dataclasses import dataclass, field, replace

from . import history, semantic
from .models import Criteria, Preferences, Recommendation
from .recommender import WEIGHTS, recommend

WIDE = 2000        # candidates kept after the filters, before grouping
LINES = 150        # lines the model reads in the final choice
BATCH = 100        # lines per background batch
KEEP = 10          # picks promoted from each batch
MIN_CANDIDATES = 10  # fewer than this and the model's optional filters are dropped
RISK_ORDER = {"bajo": 0, "medio": 1, "alto": 2}


def search(funds, profile: Preferences, criteria: Criteria | None, affinity: dict, limit: int):
    """Filter and rank the catalog. Returns candidates, diagnostics, the criteria actually applied
    and, when the model's optional filters had to be dropped, a sentence explaining it."""
    candidates, diagnostics = recommend(funds, profile, limit=limit, criteria=criteria, semantic=affinity)
    note = ""
    if criteria and len(candidates) < MIN_CANDIDATES and (criteria.keywords or criteria.min_annual_return):
        dropped = [f"que el nombre del fondo contuviera «{', '.join(criteria.keywords)}»" if criteria.keywords else "",
                   f"una rentabilidad anual mínima del {criteria.min_annual_return:.0%}"
                   if criteria.min_annual_return else ""]
        note = (f"El modelo pedía {' y '.join(part for part in dropped if part)}, pero solo "
                f"{len(candidates)} {'fondo lo cumplía' if len(candidates) == 1 else 'fondos lo cumplían'}; "
                "he retirado ese filtro para poder comparar más fondos.")
        criteria = replace(criteria, keywords=(), min_annual_return=None)
        candidates, diagnostics = recommend(funds, profile, limit=limit, criteria=criteria, semantic=affinity)
    return candidates, diagnostics, criteria, note


def theme_of(profile: Preferences, criteria: Criteria | None) -> str:
    return ", ".join(part for part in (*(criteria.keywords if criteria else ()), profile.region,
                                       profile.sector, profile.asset_class) if part)


def affinity_for(profile: Preferences, criteria: Criteria | None, conversation: str) -> dict:
    """Funds whose documented objective is close to the theme (or, without one, to what was said)."""
    try:
        return semantic.search(theme_of(profile, criteria) or ("" if criteria else conversation))
    except Exception:
        return {}


def representatives(informed: list[Recommendation]) -> tuple[list[Recommendation], dict]:
    """Best fund of each group of funds that move together, best first, and each group's size."""
    sizes: dict = {}
    for item in informed:
        if item.group is not None:
            sizes[item.group] = sizes.get(item.group, 0) + 1
    seen, leaders = set(), []
    for item in informed:
        if item.group is None:
            leaders.append(item)
        elif item.group not in seen:
            seen.add(item.group)
            leaders.append(item)
    return leaders, sizes


def final_lines(informed: list[Recommendation], winners=(), screened: int = 0, limit: int = LINES):
    """Lines for the model's final choice and how many funds they stand for.

    The best `limit` group leaders, where the picks of the background batches take the place of
    the lowest ranked. Returns (lines, funds represented by them, funds reviewed in batches).
    """
    leaders, sizes = representatives(informed)
    promoted = [item for item in leaders[limit:limit + screened] if item.fund.isin in set(winners)]
    lines = sorted(leaders[:max(limit - len(promoted), 0)] + promoted, key=lambda item: (-item.score, item.fund.isin))
    weight = lambda item: sizes.get(item.group, 1) if item.group is not None else 1
    return lines, sum(weight(item) for item in lines), sum(weight(item) for item in leaders[limit:limit + screened])


def key_of(profile: Preferences) -> tuple:
    """What the background work depends on. Soft traits and a lower risk can be applied afterwards."""
    return (profile.horizon_years, profile.currency, profile.amount, profile.region, profile.sector,
            profile.asset_class, profile.excluded_sectors)


@dataclass
class Job:
    key: tuple
    risk: str
    objective: str | None
    stop: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    criteria: Criteria | None = None
    affinity: dict = field(default_factory=dict)
    prices: object = None           # weekly prices of the wide pool
    winners: list = field(default_factory=list)
    screened: int = 0               # group leaders already seen in batches
    ready: bool = False             # criteria, pool and history are done
    error: Exception | None = None

    def usable_for(self, profile: Preferences) -> bool:
        """The work still applies: same hard data, and the risk has not gone up."""
        return (self.error is None and self.key == key_of(profile)
                and RISK_ORDER[profile.risk] <= RISK_ORDER[self.risk])

    def finish(self, timeout: float = 180.0):
        """Stop after the step in progress and wait for it."""
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout)

    def criteria_for(self, profile: Preferences) -> Criteria | None:
        """The criteria decided earlier, with the objective stated since then taken into account."""
        if self.criteria is not None and profile.objective and profile.objective != self.objective:
            return replace(self.criteria, weights=WEIGHTS[profile.objective])
        return self.criteria


def _work(job: Job, funds, profile: Preferences, conversation: str, decide, shortlist, with_documents: bool):
    try:
        job.criteria = decide(profile, conversation)
        if job.stop.is_set():
            return
        job.affinity = affinity_for(profile, job.criteria, conversation) if with_documents else {}
        candidates, _, job.criteria, _ = search(funds, profile, job.criteria, job.affinity, WIDE)
        if job.stop.is_set() or not candidates or not history.available():
            job.ready = True
            return
        job.prices = history.weekly_prices([item.fund.isin for item in candidates], profile.horizon_years)
        leaders, _ = representatives(history.inform(candidates, profile, prices=job.prices))
        job.ready = True
        while not job.stop.is_set() and LINES + job.screened < len(leaders):
            batch = leaders[LINES + job.screened:LINES + job.screened + BATCH]
            picked = shortlist(batch, profile, conversation, KEEP)
            if job.stop.is_set() and not picked:
                break
            job.winners.extend(picked)
            job.screened += len(batch)
    except Exception as exc:   # the page falls back to doing the work when asked
        job.error = exc


def start(funds, profile: Preferences, conversation: str, decide, shortlist, with_documents: bool) -> Job:
    job = Job(key=key_of(profile), risk=profile.risk, objective=profile.objective)
    job.thread = threading.Thread(target=_work, daemon=True,
                                  args=(job, funds, profile, conversation, decide, shortlist, with_documents))
    job.thread.start()
    return job
