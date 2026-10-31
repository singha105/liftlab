"""Always-valid inference with the mixture sequential probability ratio test (mSPRT).

A fixed-horizon p-value is only valid at the one sample size it was planned for. Checking it
every day and stopping at the first p < 0.05 makes false positives far more likely than 5%.
The mSPRT gives a p-value and a confidence sequence that stay valid however often you look
and whenever you stop. Johari, Pekelis & Walsh, "Always Valid Inference: Continuous
Monitoring of A/B Tests" (arXiv:1512.04922; Operations Research, 2022).

Each look at the data gives an estimate of the difference, test - control, with variance V.
Against H0: difference = theta0, with a normal mixing distribution N(theta0, gamma^2) over the
alternatives, the mixture likelihood ratio has a closed form:

    Lambda = sqrt(V / (V + gamma^2)) * exp(gamma^2 (estimate - theta0)^2 / (2 V (V + gamma^2)))

The always-valid p-value is the running minimum of min(1, 1 / Lambda) over the looks. The
confidence sequence at each look is the set of theta0 with Lambda < 1 / alpha there,
intersected with every earlier look's set.

This is the paper's two-stream test (Section 6.1) with V = var_control / n_control +
var_test / n_test. For binary data the variances are plug-in estimates, which the paper notes
is only approximately valid; `liftlab proofs` checks it by simulation.

Choosing gamma, the mixing standard deviation. It sets the size of effect the test is tuned to
find quickly. The paper (Section 5.4, eq. 12) gives the best gamma for effects drawn from
N(0, tau^2) when the test runs to at most M observations at level alpha:

    gamma^2 = tau^2 * Phi(-b) / (phi(b) / b - Phi(-b)),   b = sqrt(2 log(1/alpha) / (M tau^2))

with tau in units of one observation's standard deviation. `mixing_sd` computes it. LiftLab
uses tau = the pre-registered MDE and M = the planned users per arm: we expect effects about
the size we planned to detect, by the time we planned to read. The paper finds the test is
robust to getting gamma wrong by up to a factor of 10, so this needn't be precise.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class SequentialResult:
    """One entry per look, oldest first. p-values and intervals are always valid."""

    estimates: tuple[float, ...]
    p_values: tuple[float, ...]
    ci_low: tuple[float, ...]
    ci_high: tuple[float, ...]
    mixing_sd: float
    theta0: float
    alpha: float

    @property
    def p_value(self) -> float:
        return self.p_values[-1]

    @property
    def ci(self) -> tuple[float, float]:
        return self.ci_low[-1], self.ci_high[-1]

    @property
    def rejected(self) -> bool:
        return self.p_value <= self.alpha

    @property
    def first_rejection(self) -> int | None:
        """Index of the first look where the p-value reached alpha, if it did."""
        return next((i for i, p in enumerate(self.p_values) if p <= self.alpha), None)


def log_likelihood_ratio(
    estimate: float, variance: float, mixing_sd: float, theta0: float = 0.0
) -> float:
    """log Lambda for one look. A look with no variance yet carries no evidence: 0."""
    if not variance > 0:
        return 0.0
    g2 = mixing_sd**2
    return 0.5 * math.log(variance / (variance + g2)) + g2 * (estimate - theta0) ** 2 / (
        2 * variance * (variance + g2)
    )


def msprt(
    estimates: Sequence[float],
    variances: Sequence[float],
    *,
    mixing_sd: float,
    theta0: float = 0.0,
    alpha: float = 0.05,
) -> SequentialResult:
    """Always-valid p-values and confidence sequence over a series of looks at one experiment.

    Look k is the estimate and its variance from all the data up to then, so looks can come
    after every user or after every daily batch.
    """
    if len(estimates) != len(variances) or len(estimates) == 0:
        raise ValueError("need one variance per estimate, and at least one look")
    if not mixing_sd > 0:
        raise ValueError("mixing_sd must be positive")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")

    g2 = mixing_sd**2
    p, low, high = 1.0, -math.inf, math.inf
    p_values, lows, highs = [], [], []
    for estimate, variance in zip(estimates, variances, strict=True):
        log_lr = log_likelihood_ratio(estimate, variance, mixing_sd, theta0)
        p = min(p, math.exp(-max(log_lr, 0.0)))
        if variance > 0:
            # Lambda(theta) >= 1/alpha  <=>  (estimate - theta)^2 >= V (V + g2) / g2 * c
            c = math.log((variance + g2) / variance) - 2 * math.log(alpha)
            half = math.sqrt(variance * (variance + g2) / g2 * c)
            low, high = max(low, estimate - half), min(high, estimate + half)
        p_values.append(p)
        lows.append(low)
        highs.append(high)
    return SequentialResult(
        estimates=tuple(float(e) for e in estimates),
        p_values=tuple(p_values),
        ci_low=tuple(lows),
        ci_high=tuple(highs),
        mixing_sd=mixing_sd,
        theta0=theta0,
        alpha=alpha,
    )


def mixing_sd(prior_sd: float, unit_sd: float, max_n: float, *, alpha: float = 0.05) -> float:
    """The paper's best mixing standard deviation (eq. 12), on the scale of the difference.

    `prior_sd`: the typical effect, test - control. `unit_sd`: the standard deviation of one
    pair's difference (one user per arm), e.g. sqrt(2 p (1 - p)) for a rate near p.
    `max_n`: the most users per arm the test will run to.
    """
    if min(prior_sd, unit_sd, max_n) <= 0:
        raise ValueError("prior_sd, unit_sd and max_n must be positive")
    tau2 = (prior_sd / unit_sd) ** 2
    b = math.sqrt(2 * math.log(1 / alpha) / (max_n * tau2))
    tail = stats.norm.sf(b)
    factor = tail / (stats.norm.pdf(b) / b - tail)
    return prior_sd * math.sqrt(factor)


def proportion_looks(
    x_control: Sequence[int], n_control: Sequence[int], x_test: Sequence[int], n_test: Sequence[int]
) -> tuple[np.ndarray, np.ndarray]:
    """Estimates and plug-in variances of p_test - p_control from cumulative counts per look."""
    xc, nc = np.asarray(x_control, float), np.asarray(n_control, float)
    xt, nt = np.asarray(x_test, float), np.asarray(n_test, float)
    with np.errstate(invalid="ignore", divide="ignore"):
        pc, pt = xc / nc, xt / nt
        variance = pc * (1 - pc) / nc + pt * (1 - pt) / nt
    variance = np.where((nc > 0) & (nt > 0), variance, 0.0)
    estimate = np.where((nc > 0) & (nt > 0), pt - pc, 0.0)
    return estimate, np.nan_to_num(variance)
