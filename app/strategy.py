"""Scoring van video's en keuze/bijsturing van strategieën.

Elke strategie is een "arm" in een multi-armed bandit. Per video berekenen we een
score tussen 0 en 1 uit drie signalen:

* blijven kijken  – engagedViews / views. YouTube telt een *engaged view* pas als
  een Short niet direct wordt weggeswiped, dus 1 - deze ratio benadert het
  "weggeswiped"-percentage uit YouTube Studio.
* kijkduur        – gemiddeld bekeken percentage (Shorts loopen, dus >100% kan).
* bereik          – aantal weergaven op log-schaal.

De keuze voor de volgende video gebeurt met UCB1: strategieën met een hoge score
worden vaker gekozen, maar weinig geteste strategieën krijgen ook een kans.
"""

import math
from dataclasses import dataclass, field

WEIGHT_STAYED = 0.45
WEIGHT_RETENTION = 0.35
WEIGHT_REACH = 0.20
REACH_TARGET_VIEWS = 10_000
# Video's jonger dan dit tellen niet mee: YouTube Analytics loopt ~48 uur achter.
MIN_AGE_HOURS = 48
EXPLORATION = 0.35


def stayed_ratio(views: int, engaged_views: int | None, avg_view_percentage: float | None) -> float | None:
    """Fractie kijkers die bleef hangen (1 - weggeswiped)."""
    if views and engaged_views is not None:
        return max(0.0, min(engaged_views / views, 1.0))
    if avg_view_percentage is not None:
        return max(0.0, min(avg_view_percentage / 100, 1.0))
    return None


def score_video(views: int, engaged_views: int | None, avg_view_percentage: float | None) -> float | None:
    stayed = stayed_ratio(views, engaged_views, avg_view_percentage)
    if stayed is None:
        return None
    retention = min((avg_view_percentage or 0) / 100, 1.5) / 1.5
    reach = min(math.log10(views + 1) / math.log10(REACH_TARGET_VIEWS + 1), 1.0)
    return round(WEIGHT_STAYED * stayed + WEIGHT_RETENTION * retention + WEIGHT_REACH * reach, 4)


@dataclass
class Arm:
    strategy_id: int
    scores: list[float] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.scores)

    @property
    def mean(self) -> float | None:
        return sum(self.scores) / self.n if self.scores else None


def choose_arm(arms: list[Arm], pending: dict[int, int] | None = None) -> int:
    """Kies een strategie met UCB1.

    ``pending`` telt video's per strategie die nog geen bruikbare score hebben
    (te nieuw); die tellen mee als "geprobeerd" zodat we niet dagenlang dezelfde
    ongeteste strategie kiezen.
    """
    if not arms:
        raise ValueError("Geen actieve strategieën")
    pending = pending or {}
    tried = {a.strategy_id: a.n + pending.get(a.strategy_id, 0) for a in arms}
    untried = [a for a in arms if tried[a.strategy_id] == 0]
    if untried:
        return untried[0].strategy_id
    scored = [a for a in arms if a.n > 0]
    if not scored:
        # Alles is geprobeerd maar nog niets gescoord: kies de minst geprobeerde.
        return min(arms, key=lambda a: tried[a.strategy_id]).strategy_id
    total = sum(tried.values())
    overall = sum(a.mean for a in scored) / len(scored)

    def ucb(a: Arm) -> float:
        mean = a.mean if a.mean is not None else overall
        return mean + EXPLORATION * math.sqrt(math.log(total) / tried[a.strategy_id])

    return max(arms, key=ucb).strategy_id


def pick_losers(arms: list[Arm], min_samples: int = 3, ratio: float = 0.7, keep_at_least: int = 2) -> list[int]:
    """Strategieën die duidelijk onderpresteren en uitgezet mogen worden."""
    ranked = sorted((a for a in arms if a.n >= min_samples), key=lambda a: a.mean, reverse=True)
    if len(ranked) < 2:
        return []
    best = ranked[0].mean
    losers = [a.strategy_id for a in ranked[1:] if a.mean < best * ratio]
    max_drop = max(0, len(arms) - keep_at_least)
    return losers[::-1][:max_drop]
