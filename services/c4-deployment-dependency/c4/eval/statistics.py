"""The uncertainty around Table 4's numbers, and whether two arms really differ.

- **Bootstrap intervals**: the cases are resampled with replacement, the metric
  computed on each resample, and the 2.5th and 97.5th percentiles kept. The
  generator is seeded, so an interval is the same every time the table is
  printed from the same record.
- **McNemar's test**, exact: two arms scored on the same cases differ only
  where one is right and the other wrong. Under "they are as good as each
  other" those discordant cases split evenly, so the p value is a two sided
  binomial tail over them. An abstention counts as High, as in the scores.

Small corpora give wide intervals and large p values; the table prints them
rather than a point estimate that looks surer than it is.
"""

import random
from collections.abc import Callable, Sequence
from math import comb

from sdlc_contracts import RiskLevel

from .scoring import Scores, score

#: The seed every interval is drawn with, so a table printed twice agrees.
BOOTSTRAP_SEED = 20260928
RESAMPLES = 2000

Pairs = Sequence[tuple[RiskLevel, RiskLevel | None]]


def bootstrap(
    pairs: Pairs,
    metric: Callable[[Scores], float | None],
    *,
    resamples: int = RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float] | None:
    """A 95 percent percentile interval for one metric, or None with nothing to resample."""
    if not pairs:
        return None
    generator = random.Random(seed)
    values: list[float] = []
    for _ in range(resamples):
        drawn = [pairs[generator.randrange(len(pairs))] for _ in pairs]
        value = metric(score(list(drawn)))
        if value is not None:
            values.append(value)
    if not values:
        return None
    values.sort()
    low = values[int(0.025 * (len(values) - 1))]
    high = values[round(0.975 * (len(values) - 1))]
    return low, high


def _right(truth: RiskLevel, predicted: RiskLevel | None) -> bool:
    return (predicted or "high") == truth


def mcnemar(
    truths: Sequence[RiskLevel],
    first: Sequence[RiskLevel | None],
    second: Sequence[RiskLevel | None],
) -> dict[str, float | int]:
    """The exact two sided test of two arms on the same cases.

    `onlyFirst` counts cases the first arm got right and the second wrong, and
    `onlySecond` the reverse. With no discordant case the p value is 1.
    """
    only_first = sum(
        _right(t, a) and not _right(t, b) for t, a, b in zip(truths, first, second, strict=True)
    )
    only_second = sum(
        _right(t, b) and not _right(t, a) for t, a, b in zip(truths, first, second, strict=True)
    )
    discordant = only_first + only_second
    if not discordant:
        return {"onlyFirst": 0, "onlySecond": 0, "pValue": 1.0}
    smaller = min(only_first, only_second)
    tail = sum(comb(discordant, k) for k in range(smaller + 1)) / 2**discordant
    return {"onlyFirst": only_first, "onlySecond": only_second, "pValue": min(1.0, 2 * tail)}
