import math

import numpy as np
import pytest
from scipy import stats as sps
from statsmodels.stats.proportion import confint_proportions_2indep, proportions_ztest

from liftlab.stats.multiple import holm
from liftlab.stats.srm import srm_check
from liftlab.stats.tests import (
    ratio_estimate,
    ratio_metric,
    relative_lift,
    welch_ttest,
    ztest_proportions,
)

# SRM


def test_srm_textbook_value():
    # 5,100 vs 4,900 against 50/50: chi2 = 2 * 100^2 / 5,000 = 4.0, p = 0.0455.
    result = srm_check({"control": 5100, "test": 4900}, {"control": 0.5, "test": 0.5})
    assert result.chi2 == pytest.approx(4.0)
    assert result.p_value == pytest.approx(0.0455, abs=1e-4)
    assert not result.mismatch


@pytest.mark.parametrize(
    ("counts", "shares"),
    [((1377, 1402), (0.5, 0.5)), ((5300, 4700), (0.5, 0.5)), ((900, 2100), (0.3, 0.7))],
)
def test_srm_matches_scipy(counts, shares):
    result = srm_check(dict(zip("ct", counts, strict=True)), dict(zip("ct", shares, strict=True)))
    expected = sps.chisquare(counts, [sum(counts) * s for s in shares])
    assert result.chi2 == pytest.approx(expected.statistic)
    assert result.p_value == pytest.approx(expected.pvalue)
    assert result.mismatch == (expected.pvalue < 0.001)


def test_srm_three_arms():
    result = srm_check({"a": 340, "b": 330, "c": 330}, {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3})
    assert result.df == 2
    assert result.p_value == pytest.approx(sps.chisquare([340, 330, 330]).pvalue)


@pytest.mark.parametrize(
    ("counts", "shares", "message"),
    [
        ({"c": 1, "t": 1}, {"c": 0.5, "x": 0.5}, "same arms"),
        ({"c": 1, "t": 1}, {"c": 0.6, "t": 0.6}, "add up to 1"),
        ({"c": 0, "t": 0}, {"c": 0.5, "t": 0.5}, "no users"),
        ({"c": 1}, {"c": 1.0}, "two arms"),
    ],
)
def test_srm_rejects_bad_input(counts, shares, message):
    with pytest.raises(ValueError, match=message):
        srm_check(counts, shares)


# Two proportions


@pytest.mark.parametrize(
    ("x_c", "n_c", "x_t", "n_t"),
    [(413, 1377, 482, 1377), (90, 300, 70, 310), (5, 40, 9, 41), (4302, 9645, 4276, 9271)],
)
def test_ztest_matches_statsmodels(x_c, n_c, x_t, n_t):
    ours = ztest_proportions(x_c, n_c, x_t, n_t)
    z, p = proportions_ztest([x_t, x_c], [n_t, n_c])
    low, high = confint_proportions_2indep(x_t, n_t, x_c, n_c, method="wald")
    assert ours.statistic == pytest.approx(z)
    assert ours.p_value == pytest.approx(p)
    assert ours.ci == pytest.approx((low, high))
    assert ours.diff == pytest.approx(x_t / n_t - x_c / n_c)
    assert ours.relative == pytest.approx((x_t / n_t) / (x_c / n_c) - 1)


def test_relative_lift_by_hand():
    # 30% -> 35% with variances 0.0002 and 0.0003: lift 1/6,
    # se = sqrt(0.0003 / 0.09 + 0.35^2 * 0.0002 / 0.3^4).
    lift, (low, high) = relative_lift(0.30, 0.35, 0.0002, 0.0003)
    se = math.sqrt(0.0003 / 0.09 + 0.35**2 * 0.0002 / 0.3**4)
    assert lift == pytest.approx(1 / 6)
    assert (high - low) / 2 == pytest.approx(1.959964 * se, rel=1e-6)


def test_ztest_false_positive_rate_and_coverage():
    """A/A on Bernoulli data: 5% false positives, and the CI covers the truth 95% of the time."""
    rng = np.random.default_rng(5)
    reps, n, p = 4000, 1000, 0.3
    x_c, x_same, x_t = (rng.binomial(n, rate, reps) for rate in (p, p, p + 0.05))
    a_a = [
        ztest_proportions(int(a), n, int(b), n).significant
        for a, b in zip(x_c, x_same, strict=True)
    ]
    covered = []
    for a, b in zip(x_c, x_t, strict=True):
        result = ztest_proportions(int(a), n, int(b), n)
        covered.append(result.ci[0] <= 0.05 <= result.ci[1])
    assert np.mean(a_a) == pytest.approx(0.05, abs=0.015)
    assert np.mean(covered) == pytest.approx(0.95, abs=0.015)


# Welch


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_welch_matches_scipy(seed):
    rng = np.random.default_rng(seed)
    control = rng.poisson(1.4, 300).astype(float)
    test = rng.poisson(1.7, 280) * rng.integers(1, 3, 280)
    ours = welch_ttest(control, test)
    theirs = sps.ttest_ind(test, control, equal_var=False)
    assert ours.statistic == pytest.approx(theirs.statistic)
    assert ours.p_value == pytest.approx(theirs.pvalue)
    assert ours.df == pytest.approx(theirs.df)
    assert ours.ci == pytest.approx(tuple(theirs.confidence_interval(0.95)))


def test_welch_rejects_constant_arms():
    with pytest.raises(ValueError, match="constant"):
        welch_ttest([1.0, 1.0, 1.0], [1.0, 1.0])


# Ratio metrics, delta method


def test_ratio_estimate_by_hand():
    # Linearization: R = sum(y)/sum(x), L_i = (y_i - R x_i) / mean(x), Var(R) = var(L) / n.
    y = np.array([0, 1, 2, 0, 3, 1], dtype=float)
    x = np.array([2, 1, 4, 1, 5, 3], dtype=float)
    ratio = y.sum() / x.sum()
    linear = (y - ratio * x) / x.mean()
    result = ratio_estimate(y, x)
    assert result.ratio == pytest.approx(7 / 16)
    assert result.variance == pytest.approx(linear.var(ddof=1) / len(y))


def test_ratio_with_unit_denominators_is_a_mean():
    rng = np.random.default_rng(4)
    c, t = rng.poisson(2, 500).astype(float), rng.poisson(2.2, 450).astype(float)
    ratio = ratio_metric(c, np.ones_like(c), t, np.ones_like(t))
    welch = welch_ttest(c, t)
    assert ratio.diff == pytest.approx(welch.diff)
    assert ratio.se == pytest.approx(welch.se)


def _abandon_data(rng, users, p_mean):
    """Sessions per user vary, and each user abandons at their own rate: clustered data."""
    ended = rng.poisson(2.0, users) + 1
    own_rate = rng.beta(2, 2 * (1 - p_mean) / p_mean, users)
    return rng.binomial(ended, own_rate).astype(float), ended.astype(float)


def test_delta_method_covers_but_session_level_doesnt():
    """With clustered sessions the delta-method CI holds 95%; treating sessions as independent
    gives an interval that's too narrow."""
    rng = np.random.default_rng(11)
    truth_c, truth_t = 0.2, 0.2  # abandon rate = mean of own_rate, weighted by sessions
    big = [_abandon_data(rng, 400_000, p) for p in (truth_c, truth_t)]
    true_diff = big[1][0].sum() / big[1][1].sum() - big[0][0].sum() / big[0][1].sum()
    delta, naive = [], []
    for _ in range(1500):
        (yc, xc), (yt, xt) = _abandon_data(rng, 600, truth_c), _abandon_data(rng, 600, truth_t)
        result = ratio_metric(yc, xc, yt, xt)
        delta.append(result.ci[0] <= true_diff <= result.ci[1])
        naive_result = ztest_proportions(int(yc.sum()), int(xc.sum()), int(yt.sum()), int(xt.sum()))
        naive.append(naive_result.ci[0] <= true_diff <= naive_result.ci[1])
    assert np.mean(delta) == pytest.approx(0.95, abs=0.015)
    # 1,500 runs pin coverage to about +-0.6 points, so this is well clear of 95%.
    assert np.mean(naive) < 0.935


# Holm


@pytest.mark.parametrize(
    "p_values",
    [[0.01, 0.04, 0.03], [0.2], [0.001, 0.5, 0.012, 0.012, 0.9], [0.04, 0.03, 0.02, 0.01]],
)
def test_holm_matches_statsmodels(p_values):
    from statsmodels.stats.multitest import multipletests

    reject, adjusted, _, _ = multipletests(p_values, alpha=0.05, method="holm")
    result = holm(p_values)
    assert result.adjusted == pytest.approx(tuple(adjusted))
    assert result.reject == tuple(bool(r) for r in reject)


def test_holm_controls_family_wise_error():
    rng = np.random.default_rng(2)
    any_false = [any(holm(list(rng.random(4))).reject) for _ in range(10_000)]
    unadjusted = [any(p < 0.05 for p in rng.random(4)) for _ in range(10_000)]
    assert np.mean(any_false) <= 0.05 + 0.005
    assert np.mean(unadjusted) == pytest.approx(1 - 0.95**4, abs=0.01)
