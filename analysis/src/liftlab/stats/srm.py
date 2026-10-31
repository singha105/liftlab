"""Sample ratio mismatch: does each arm have the users the allocation says it should?

A chi-square goodness-of-fit test of users per arm against the planned shares. A fair 50/50
split rarely lands exactly on 50/50, but it lands close. p < 0.001 means the gap is too big
for chance: something between assignment and logging loses users unevenly, and no metric
from the run can be trusted, whatever it shows.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from scipy import stats

THRESHOLD = 0.001


@dataclass(frozen=True)
class SRMResult:
    observed: dict[str, int]
    expected: dict[str, float]
    chi2: float
    df: int
    p_value: float
    threshold: float

    @property
    def mismatch(self) -> bool:
        return self.p_value < self.threshold


def srm_check(
    counts: Mapping[str, int], allocation: Mapping[str, float], *, threshold: float = THRESHOLD
) -> SRMResult:
    """Chi-square test of `counts` (users per arm) against `allocation` (planned shares)."""
    if set(counts) != set(allocation):
        raise ValueError("counts and allocation must name the same arms")
    if len(allocation) < 2:
        raise ValueError("an experiment needs at least two arms")
    if any(share <= 0 for share in allocation.values()):
        raise ValueError("every planned share must be positive")
    if abs(sum(allocation.values()) - 1) > 1e-9:
        raise ValueError("planned shares must add up to 1")
    if any(count < 0 for count in counts.values()):
        raise ValueError("counts can't be negative")
    total = sum(counts.values())
    if total == 0:
        raise ValueError("no users to check")

    arms = list(allocation)
    expected = {arm: total * allocation[arm] for arm in arms}
    chi2 = sum((counts[arm] - expected[arm]) ** 2 / expected[arm] for arm in arms)
    df = len(arms) - 1
    return SRMResult(
        observed={arm: int(counts[arm]) for arm in arms},
        expected=expected,
        chi2=float(chi2),
        df=df,
        p_value=float(stats.chi2.sf(chi2, df)),
        threshold=threshold,
    )
