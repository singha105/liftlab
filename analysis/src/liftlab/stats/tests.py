"""Fixed-horizon tests for test minus control, with absolute and relative lift.

- `ztest_proportions`: a rate per user, like activation. Pooled z-test, Wald interval.
- `welch_ttest`: a mean per user, like sessions in 7 days. Welch's t-test, which doesn't
  assume the arms have equal variances.
- `ratio_metric`: a ratio of sums where the user isn't the unit of the ratio, like abandoned
  sessions / ended sessions. Users are still the unit of randomization, and one user's
  sessions aren't independent of each other, so the variance comes from the delta method
  with the user as the unit.

The relative lift is test / control - 1. Its interval uses the delta method on the ratio of
two independent means, so it's symmetric around the estimate; it needs a control well away
from zero, which every metric here has.
"""

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike
from scipy import stats


@dataclass(frozen=True)
class Comparison:
    """Test minus control. Intervals are at 1 - alpha."""

    method: str
    n_control: int
    n_test: int
    control: float  # the metric in each arm: a rate, a mean or a ratio
    test: float
    diff: float
    se: float  # of diff, unpooled
    ci: tuple[float, float]
    relative: float
    relative_ci: tuple[float, float]
    statistic: float  # z, or t for Welch
    p_value: float
    alpha: float
    df: float | None = None

    @property
    def significant(self) -> bool:
        return self.p_value < self.alpha


@dataclass(frozen=True)
class RatioEstimate:
    """sum(numerator) / sum(denominator) over n units, with its delta-method variance."""

    n: int
    ratio: float
    variance: float


def ztest_proportions(
    x_control: int, n_control: int, x_test: int, n_test: int, *, alpha: float = 0.05
) -> Comparison:
    """Two-sided z-test of two proportions: pooled rate for the test, unpooled for the CI.

    Matches statsmodels' `proportions_ztest` and `confint_proportions_2indep(method="wald")`.
    """
    _check_alpha(alpha)
    for x, n in ((x_control, n_control), (x_test, n_test)):
        if n <= 0 or not 0 <= x <= n:
            raise ValueError("each arm needs n > 0 and 0 <= x <= n")
    p_c, p_t = x_control / n_control, x_test / n_test
    var_c, var_t = p_c * (1 - p_c) / n_control, p_t * (1 - p_t) / n_test
    pooled = (x_control + x_test) / (n_control + n_test)
    se_null = math.sqrt(pooled * (1 - pooled) * (1 / n_control + 1 / n_test))
    diff = p_t - p_c
    z = diff / se_null if se_null else 0.0
    return _compare(
        "two-proportion z-test",
        n_control,
        n_test,
        p_c,
        p_t,
        var_c,
        var_t,
        alpha,
        z,
        2 * stats.norm.sf(abs(z)),
    )


def welch_ttest(control: ArrayLike, test: ArrayLike, *, alpha: float = 0.05) -> Comparison:
    """Welch's t-test for a difference in means, with a t interval on the Welch df.

    Matches scipy's `ttest_ind(equal_var=False)` and its `confidence_interval`.
    """
    _check_alpha(alpha)
    c, t = _values(control), _values(test)
    if len(c) < 2 or len(t) < 2:
        raise ValueError("each arm needs at least two values")
    var_c, var_t = c.var(ddof=1) / len(c), t.var(ddof=1) / len(t)
    se = math.sqrt(var_c + var_t)
    if se == 0:
        raise ValueError("both arms are constant, so there's nothing to test")
    df = se**4 / (var_c**2 / (len(c) - 1) + var_t**2 / (len(t) - 1))
    diff = float(t.mean() - c.mean())
    t_stat = diff / se
    half = stats.t.ppf(1 - alpha / 2, df) * se
    result = _compare(
        "Welch t-test",
        len(c),
        len(t),
        float(c.mean()),
        float(t.mean()),
        var_c,
        var_t,
        alpha,
        t_stat,
        2 * stats.t.sf(abs(t_stat), df),
        df,
    )
    return _replace_ci(result, (diff - half, diff + half))


def ratio_estimate(numerator: ArrayLike, denominator: ArrayLike) -> RatioEstimate:
    """sum(numerator) / sum(denominator), one pair per unit, with its delta-method variance.

    Var(R) ~ (s_y^2 - 2 R s_xy + R^2 s_x^2) / (n * xbar^2), with sample (co)variances.
    """
    y, x = _values(numerator), _values(denominator)
    if len(y) != len(x):
        raise ValueError("numerator and denominator need one value per unit")
    if len(y) < 2:
        raise ValueError("need at least two units")
    if x.sum() <= 0:
        raise ValueError("the denominator sums to zero")
    ratio = y.sum() / x.sum()
    cov = np.cov(y, x, ddof=1)
    variance = (cov[0, 0] - 2 * ratio * cov[0, 1] + ratio**2 * cov[1, 1]) / (len(y) * x.mean() ** 2)
    return RatioEstimate(len(y), float(ratio), float(max(variance, 0.0)))


def ratio_metric(
    numerator_control: ArrayLike,
    denominator_control: ArrayLike,
    numerator_test: ArrayLike,
    denominator_test: ArrayLike,
    *,
    alpha: float = 0.05,
) -> Comparison:
    """Difference of two ratio metrics, z-test and normal interval on delta-method variances."""
    _check_alpha(alpha)
    c = ratio_estimate(numerator_control, denominator_control)
    t = ratio_estimate(numerator_test, denominator_test)
    se = math.sqrt(c.variance + t.variance)
    if se == 0:
        raise ValueError("both ratios have zero variance, so there's nothing to test")
    z = (t.ratio - c.ratio) / se
    return _compare(
        "delta-method z-test",
        c.n,
        t.n,
        c.ratio,
        t.ratio,
        c.variance,
        t.variance,
        alpha,
        z,
        2 * stats.norm.sf(abs(z)),
    )


def relative_lift(
    control: float, test: float, var_control: float, var_test: float, *, alpha: float = 0.05
) -> tuple[float, tuple[float, float]]:
    """test / control - 1 and its delta-method interval, for independent arm estimates."""
    if control == 0:
        return math.nan, (math.nan, math.nan)
    lift = test / control - 1
    se = math.sqrt(var_test / control**2 + test**2 * var_control / control**4)
    half = stats.norm.ppf(1 - alpha / 2) * se
    return lift, (lift - half, lift + half)


def _compare(
    method, n_c, n_t, control, test, var_c, var_t, alpha, statistic, p_value, df=None
) -> Comparison:
    diff = test - control
    se = math.sqrt(var_c + var_t)
    half = stats.norm.ppf(1 - alpha / 2) * se
    relative, relative_ci = relative_lift(control, test, var_c, var_t, alpha=alpha)
    return Comparison(
        method=method,
        n_control=int(n_c),
        n_test=int(n_t),
        control=float(control),
        test=float(test),
        diff=float(diff),
        se=se,
        ci=(diff - half, diff + half),
        relative=relative,
        relative_ci=relative_ci,
        statistic=float(statistic),
        p_value=float(p_value),
        alpha=alpha,
        df=None if df is None else float(df),
    )


def _replace_ci(result: Comparison, ci: tuple[float, float]) -> Comparison:
    return Comparison(**{**result.__dict__, "ci": (float(ci[0]), float(ci[1]))})


def _values(values: ArrayLike) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        raise ValueError("expected one value per unit")
    if not np.isfinite(array).all():
        raise ValueError("values must be finite")
    return array


def _check_alpha(alpha: float) -> None:
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
