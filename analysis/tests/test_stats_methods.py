import math

import numpy as np
import pytest
import statsmodels.api as sm
from scipy import stats as sps

from liftlab.stats.bootstrap import bootstrap_ci
from liftlab.stats.cuped import cuped
from liftlab.stats.sequential import log_likelihood_ratio, mixing_sd, msprt, proportion_looks

# Bootstrap


def _mean(sample):
    return sample.mean(axis=1)


def test_bootstrap_matches_scipy_percentile():
    rng = np.random.default_rng(0)
    data = rng.exponential(2.0, 300)
    ours = bootstrap_ci(_mean, data, n_resamples=20_000, seed=1)
    theirs = sps.bootstrap(
        (data,), np.mean, n_resamples=20_000, method="percentile", rng=np.random.default_rng(2)
    ).confidence_interval
    width = theirs.high - theirs.low
    assert ours.estimate == pytest.approx(data.mean())
    assert ours.ci[0] == pytest.approx(theirs.low, abs=0.03 * width)
    assert ours.ci[1] == pytest.approx(theirs.high, abs=0.03 * width)


def test_bootstrap_two_samples_and_quantiles():
    rng = np.random.default_rng(3)
    control, test = rng.lognormal(6.5, 0.5, 800), rng.lognormal(6.6, 0.5, 700)

    def p75_diff(c, t):
        return np.quantile(t, 0.75, axis=1) - np.quantile(c, 0.75, axis=1)

    ours = bootstrap_ci(p75_diff, control, test, n_resamples=10_000, seed=4)
    theirs = sps.bootstrap(
        (control, test),
        lambda c, t, axis: np.quantile(t, 0.75, axis=axis) - np.quantile(c, 0.75, axis=axis),
        n_resamples=10_000,
        method="percentile",
        rng=np.random.default_rng(5),
    ).confidence_interval
    width = theirs.high - theirs.low
    assert ours.ci[0] == pytest.approx(theirs.low, abs=0.05 * width)
    assert ours.ci[1] == pytest.approx(theirs.high, abs=0.05 * width)


def test_bootstrap_is_seedable_and_resamples_rows():
    rng = np.random.default_rng(6)
    rows = np.where(rng.random((200, 5)) < 0.6, rng.normal(1000, 200, (200, 5)), np.nan)

    def p75(sample):  # one row per user, NaN padding: resample users, not values
        return np.nanquantile(sample.reshape(len(sample), -1), 0.75, axis=1)

    first = bootstrap_ci(p75, rows, n_resamples=500, seed=7)
    again = bootstrap_ci(p75, rows, n_resamples=500, seed=7)
    assert first == again
    assert first.estimate == pytest.approx(np.nanquantile(rows, 0.75))


def test_bootstrap_coverage():
    rng = np.random.default_rng(8)
    covered = []
    for _ in range(300):
        data = rng.exponential(1.0, 200)
        result = bootstrap_ci(_mean, data, n_resamples=1000, seed=rng)
        covered.append(result.ci[0] <= 1.0 <= result.ci[1])
    assert np.mean(covered) == pytest.approx(0.95, abs=0.035)


def test_bootstrap_rejects_bad_statistic():
    with pytest.raises(ValueError, match="one value per resample"):
        bootstrap_ci(lambda s: s.mean(), np.arange(10.0))


# CUPED


def _pre_post(rng, n, effect, rho=0.7):
    pre = rng.normal(0, 1, n)
    treated = rng.random(n) < 0.5
    post = rho * pre + math.sqrt(1 - rho**2) * rng.normal(0, 1, n) + effect * treated
    return post, treated, pre


def test_cuped_estimate_is_the_ancova_coefficient():
    rng = np.random.default_rng(9)
    y, treated, x = _pre_post(rng, 2000, 0.1)
    result = cuped(y, treated, x)
    design = sm.add_constant(np.column_stack([treated.astype(float), x]))
    fit = sm.OLS(y, design).fit(cov_type="HC2")
    assert result.estimate == pytest.approx(fit.params[1], rel=1e-10)
    assert result.theta[0] == pytest.approx(fit.params[2], rel=1e-10)
    assert result.se == pytest.approx(fit.bse[1], rel=0.01)
    assert result.unadjusted_estimate == pytest.approx(y[treated].mean() - y[~treated].mean())


def test_cuped_with_categorical_covariates():
    rng = np.random.default_rng(10)
    n = 3000
    device = rng.integers(0, 3, n)
    treated = rng.random(n) < 0.5
    y = (rng.random(n) < 0.25 + 0.1 * device + 0.04 * treated).astype(float)
    dummies = np.eye(3)[device][:, 1:]
    result = cuped(y, treated, dummies)
    fit = sm.OLS(y, sm.add_constant(np.column_stack([treated, dummies]).astype(float))).fit()
    assert result.estimate == pytest.approx(fit.params[1], rel=1e-10)
    assert result.variance_reduction > 0


def test_cuped_constant_covariate_changes_nothing():
    rng = np.random.default_rng(11)
    y, treated, _ = _pre_post(rng, 500, 0.0)
    result = cuped(y, treated, np.zeros(500))
    assert result.estimate == pytest.approx(result.unadjusted_estimate)
    assert result.variance_reduction == pytest.approx(0.0, abs=1e-12)


def test_cuped_is_unbiased_covers_and_removes_rho_squared():
    rng = np.random.default_rng(12)
    rho, effect = 0.7, 0.1
    estimates, raw, covered, reductions = [], [], [], []
    for _ in range(800):
        result = cuped(*_pre_post(rng, 1000, effect, rho))
        estimates.append(result.estimate)
        raw.append(result.unadjusted_estimate)
        covered.append(result.ci[0] <= effect <= result.ci[1])
        reductions.append(result.variance_reduction)
    assert np.mean(estimates) == pytest.approx(effect, abs=0.004)
    assert np.mean(covered) == pytest.approx(0.95, abs=0.02)
    # Reported reduction matches rho^2, and so does the real spread across experiments.
    assert np.mean(reductions) == pytest.approx(rho**2, abs=0.01)
    assert 1 - np.var(estimates) / np.var(raw) == pytest.approx(rho**2, abs=0.06)


# mSPRT


def test_likelihood_ratio_by_hand():
    # V = 0.0004, gamma = 0.05, estimate 0.06:
    # log Lambda = 0.5 log(0.0004 / 0.0029) + 0.0025 * 0.0036 / (2 * 0.0004 * 0.0029)
    expected = 0.5 * math.log(0.0004 / 0.0029) + 0.0025 * 0.0036 / (2 * 0.0004 * 0.0029)
    assert log_likelihood_ratio(0.06, 0.0004, 0.05) == pytest.approx(expected)
    assert log_likelihood_ratio(0.06, 0.0, 0.05) == 0.0


def test_likelihood_ratio_matches_numerical_mixture():
    """Lambda is the N(0, V) likelihood ratio averaged over theta ~ N(theta0, gamma^2)."""
    estimate, variance, gamma, theta0 = 0.031, 0.00021, 0.04, 0.005
    thetas = np.linspace(theta0 - 10 * gamma, theta0 + 10 * gamma, 200_001)
    ratio = sps.norm.pdf(estimate, thetas, math.sqrt(variance)) / sps.norm.pdf(
        estimate, theta0, math.sqrt(variance)
    )
    mixture = np.trapezoid(ratio * sps.norm.pdf(thetas, theta0, gamma), thetas)
    assert log_likelihood_ratio(estimate, variance, gamma, theta0) == pytest.approx(
        math.log(mixture), rel=1e-6
    )


def test_confidence_sequence_edges_sit_on_the_threshold():
    result = msprt([0.04], [0.0002], mixing_sd=0.05, alpha=0.05)
    for edge in result.ci:
        assert log_likelihood_ratio(0.04, 0.0002, 0.05, theta0=edge) == pytest.approx(math.log(20))


def test_p_values_never_rise_and_intervals_only_shrink():
    rng = np.random.default_rng(13)
    n = np.arange(1, 301) * 20
    x_c, x_t = np.cumsum(rng.binomial(20, 0.3, 300)), np.cumsum(rng.binomial(20, 0.3, 300))
    result = msprt(*proportion_looks(x_c, n, x_t, n), mixing_sd=0.05)
    assert all(np.diff(result.p_values) <= 0)
    assert all(np.diff(result.ci_low) >= 0) and all(np.diff(result.ci_high) <= 0)


def test_mixing_sd_by_hand():
    # tau in unit-sd terms: 0.05 / sqrt(0.42); b = sqrt(2 log 20 / (1377 tau^2)).
    tau2 = 0.05**2 / 0.42
    b = math.sqrt(2 * math.log(20) / (1377 * tau2))
    factor = sps.norm.sf(b) / (sps.norm.pdf(b) / b - sps.norm.sf(b))
    assert mixing_sd(0.05, math.sqrt(0.42), 1377) == pytest.approx(0.05 * math.sqrt(factor))
    assert mixing_sd(0.05, math.sqrt(0.42), 1377) == pytest.approx(0.0620, abs=5e-4)


def test_msprt_stays_valid_under_continuous_monitoring():
    """Normal data, a look after every pair: the mSPRT keeps false positives under 5% while a
    fixed-horizon z-test checked at every look doesn't come close."""
    rng = np.random.default_rng(14)
    paths, looks = 2000, 500
    pairs = rng.normal(0, math.sqrt(2), (paths, looks))  # test - control, one pair per look
    n = np.arange(1, looks + 1)
    estimates = pairs.cumsum(axis=1) / n
    variances = 2 / n
    sequential = [
        msprt(e, variances, mixing_sd=0.2).rejected for e in estimates
    ]  # gamma ~ effects of 0.2 sd
    naive = (np.abs(estimates / np.sqrt(variances)) > 1.959964).any(axis=1)
    assert np.mean(sequential) <= 0.05
    assert np.mean(naive) > 0.25
