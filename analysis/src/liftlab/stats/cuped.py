"""CUPED: a smaller variance for the same experiment, using what users did before it.

Each user's outcome is adjusted by how far their pre-period behavior was from average:
Y' = Y - theta * (X - mean(X)). X was fixed before assignment, so the adjustment can't
introduce bias, and the more X predicts Y the more noise it removes: the variance falls by
about corr(X, Y)^2. Deng, Xu, Kohavi & Walker (2013).

theta comes from regressing Y on X within each arm, so the estimate is exactly the arm
coefficient of the regression Y ~ arm + X. With several covariates (dummy-coded categories,
say) this is regression adjustment, which EXP-001 uses as a sensitivity check. A covariate
that's constant, like pre-period sessions for new users, adjusts nothing.
"""

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike
from scipy import stats


@dataclass(frozen=True)
class CupedResult:
    """Test minus control, adjusted and unadjusted. Intervals are normal, at 1 - alpha."""

    n_control: int
    n_test: int
    estimate: float
    se: float
    ci: tuple[float, float]
    p_value: float
    unadjusted_estimate: float
    unadjusted_se: float
    unadjusted_ci: tuple[float, float]
    theta: tuple[float, ...]
    alpha: float

    @property
    def variance_reduction(self) -> float:
        """Share of the estimate's variance the adjustment removed: 0.4 means 40%."""
        return 1 - (self.se / self.unadjusted_se) ** 2

    @property
    def ci_width_reduction(self) -> float:
        return 1 - self.se / self.unadjusted_se


def cuped(
    outcome: ArrayLike, treated: ArrayLike, covariates: ArrayLike, *, alpha: float = 0.05
) -> CupedResult:
    """CUPED-adjusted difference in means, test minus control.

    `covariates` is one pre-period value per user, or a 2-D array with one column each.
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    y = np.asarray(outcome, dtype=float)
    arm = np.asarray(treated, dtype=bool)
    x = np.asarray(covariates, dtype=float)
    x = x[:, None] if x.ndim == 1 else x
    if y.ndim != 1 or arm.shape != y.shape or x.ndim != 2 or len(x) != len(y):
        raise ValueError("outcome, treated and covariates need one row per user")
    if not (np.isfinite(y).all() and np.isfinite(x).all()):
        raise ValueError("values must be finite")
    n_t, n_c = int(arm.sum()), int((~arm).sum())
    if min(n_t, n_c) < 2:
        raise ValueError("each arm needs at least two users")

    # Within-arm centering gives the pooled within-arm slope, i.e. the ANCOVA theta.
    xc, yc = x.copy(), y.copy()
    for group in (arm, ~arm):
        xc[group] -= x[group].mean(axis=0)
        yc[group] -= y[group].mean()
    theta = np.linalg.lstsq(xc, yc, rcond=None)[0]
    adjusted = y - (x - x.mean(axis=0)) @ theta

    z = stats.norm.ppf(1 - alpha / 2)
    raw_est, raw_se = _diff(y, arm)
    est, se = _diff(adjusted, arm)
    return CupedResult(
        n_control=n_c,
        n_test=n_t,
        estimate=est,
        se=se,
        ci=(est - z * se, est + z * se),
        p_value=float(2 * stats.norm.sf(abs(est / se))) if se else math.nan,
        unadjusted_estimate=raw_est,
        unadjusted_se=raw_se,
        unadjusted_ci=(raw_est - z * raw_se, raw_est + z * raw_se),
        theta=tuple(float(v) for v in theta),
        alpha=alpha,
    )


def _diff(values: np.ndarray, arm: np.ndarray) -> tuple[float, float]:
    t, c = values[arm], values[~arm]
    se = math.sqrt(t.var(ddof=1) / len(t) + c.var(ddof=1) / len(c))
    return float(t.mean() - c.mean()), se
