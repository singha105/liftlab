"""Sample size, minimum detectable effect and duration for a two-arm experiment.

Everything uses the normal approximation with equal arms, two-sided by default, and agrees
with statsmodels. For proportions the test uses the pooled rate under the null and each arm's
own rate under the alternative, as `power_proportions_2indep` does; for means the standard
deviation is treated as known, as `NormalIndPower` does.

An effect is the change from control to test: positive for an increase. With
`alternative="larger"` it must be positive, with `"smaller"` negative. A sample size is the
smallest whole number of users per arm that reaches the target power.
"""

import math
from statistics import NormalDist

ALTERNATIVES = ("two-sided", "larger", "smaller")

_Z = NormalDist()


def power_proportions(
    baseline: float,
    mde: float,
    n_per_arm: float,
    *,
    relative: bool = False,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> float:
    diff = _check_proportions(baseline, mde, relative, alpha, None, alternative)
    return _power(diff, n_per_arm, *_sd_proportions(baseline, diff), alpha, alternative)


def sample_size_proportions(
    baseline: float,
    mde: float,
    *,
    relative: bool = False,
    alpha: float = 0.05,
    power: float = 0.80,
    alternative: str = "two-sided",
) -> int:
    diff = _check_proportions(baseline, mde, relative, alpha, power, alternative)
    return _sample_size(diff, *_sd_proportions(baseline, diff), alpha, power, alternative)


def mde_proportions(
    baseline: float,
    n_per_arm: float,
    *,
    relative: bool = False,
    alpha: float = 0.05,
    power: float = 0.80,
    alternative: str = "two-sided",
) -> float:
    """The smallest change the test detects with `power`: an increase unless `"smaller"`."""
    _check_proportions(baseline, None, relative, alpha, power, alternative)
    sign = -1 if alternative == "smaller" else 1
    room = baseline if sign < 0 else 1 - baseline

    def power_at(d: float) -> float:
        return _power(sign * d, n_per_arm, *_sd_proportions(baseline, sign * d), alpha, alternative)

    diff = sign * _solve(power_at, power, room)
    return diff / baseline if relative else diff


def power_means(
    baseline: float,
    sd: float,
    mde: float,
    n_per_arm: float,
    *,
    relative: bool = False,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> float:
    diff = _check_means(baseline, sd, mde, relative, alpha, None, alternative)
    return _power(diff, n_per_arm, sd * math.sqrt(2), sd * math.sqrt(2), alpha, alternative)


def sample_size_means(
    baseline: float,
    sd: float,
    mde: float,
    *,
    relative: bool = False,
    alpha: float = 0.05,
    power: float = 0.80,
    alternative: str = "two-sided",
) -> int:
    """`baseline` is the control mean; it only matters for a relative `mde`."""
    diff = _check_means(baseline, sd, mde, relative, alpha, power, alternative)
    return _sample_size(diff, sd * math.sqrt(2), sd * math.sqrt(2), alpha, power, alternative)


def mde_means(
    baseline: float,
    sd: float,
    n_per_arm: float,
    *,
    relative: bool = False,
    alpha: float = 0.05,
    power: float = 0.80,
    alternative: str = "two-sided",
) -> float:
    _check_means(baseline, sd, None, relative, alpha, power, alternative)
    sign = -1 if alternative == "smaller" else 1
    s = sd * math.sqrt(2)
    diff = sign * _solve(
        lambda d: _power(sign * d, n_per_arm, s, s, alpha, alternative), power, 1e3 * sd
    )
    return diff / baseline if relative else diff


def duration_days(n_per_arm: int, daily_eligible: float, *, arms: int = 2) -> int:
    """Whole days until every arm has `n_per_arm` users, at `daily_eligible` new users a day."""
    if daily_eligible <= 0:
        raise ValueError("daily_eligible must be positive")
    return math.ceil(n_per_arm * arms / daily_eligible)


def _power(diff, n, sd_null, sd_alt, alpha, alternative) -> float:
    """Power of the z-test, where sd_null and sd_alt are per-pair: sqrt(var_test + var_control)."""
    shift = diff * math.sqrt(n) / sd_alt
    ratio = sd_null / sd_alt
    crit = _Z.inv_cdf(1 - alpha / 2 if alternative == "two-sided" else 1 - alpha)
    power = 0.0
    if alternative in ("two-sided", "larger"):
        power += _Z.cdf(shift - crit * ratio)
    if alternative in ("two-sided", "smaller"):
        power += _Z.cdf(-crit * ratio - shift)
    return power


def _sample_size(diff, sd_null, sd_alt, alpha, power, alternative) -> int:
    crit = _Z.inv_cdf(1 - alpha / 2 if alternative == "two-sided" else 1 - alpha)
    # The one-tail formula, then a nudge either way for the other tail and rounding.
    n = max(2, math.ceil(((crit * sd_null + _Z.inv_cdf(power) * sd_alt) / diff) ** 2))
    while n > 2 and _power(diff, n - 1, sd_null, sd_alt, alpha, alternative) >= power:
        n -= 1
    while _power(diff, n, sd_null, sd_alt, alpha, alternative) < power:
        n += 1
    return n


def _solve(power_at, target: float, upper: float) -> float:
    """The effect size in (0, upper) where power_at reaches target, by bisection."""
    hi = upper * (1 - 1e-12)
    if power_at(hi) < target:
        raise ValueError("no effect this sample can detect reaches the target power")
    lo = 0.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if power_at(mid) < target else (lo, mid)
    return hi


def _check(alpha, power, alternative) -> None:
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    if power is not None and not alpha < power < 1:
        raise ValueError("power must be between alpha and 1")
    if alternative not in ALTERNATIVES:
        raise ValueError(f"alternative must be one of {ALTERNATIVES}")


def _check_direction(diff, alternative) -> None:
    if diff == 0:
        raise ValueError("mde must not be zero")
    if (alternative == "larger" and diff < 0) or (alternative == "smaller" and diff > 0):
        raise ValueError(f"an mde of {diff:+g} can't be detected by a {alternative!r} test")


def _check_proportions(baseline, mde, relative, alpha, power, alternative) -> float | None:
    _check(alpha, power, alternative)
    if not 0 < baseline < 1:
        raise ValueError("baseline must be a rate between 0 and 1")
    if mde is None:
        return None
    diff = mde * baseline if relative else mde
    _check_direction(diff, alternative)
    if not 0 < baseline + diff < 1:
        raise ValueError(f"baseline {baseline:g} with mde {diff:+g} leaves the 0-1 range")
    return diff


def _check_means(baseline, sd, mde, relative, alpha, power, alternative) -> float | None:
    _check(alpha, power, alternative)
    if sd <= 0:
        raise ValueError("sd must be positive")
    if relative and baseline == 0:
        raise ValueError("a relative mde needs a non-zero baseline")
    if mde is None:
        return None
    diff = mde * baseline if relative else mde
    _check_direction(diff, alternative)
    return diff


def _sd_proportions(baseline: float, diff: float) -> tuple[float, float]:
    test = baseline + diff
    pooled = baseline + diff / 2
    return (
        math.sqrt(2 * pooled * (1 - pooled)),
        math.sqrt(test * (1 - test) + baseline * (1 - baseline)),
    )
