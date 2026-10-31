"""The power module against statsmodels, which is a test-only dependency."""

import math

import pytest
from statsmodels.stats.power import NormalIndPower, TTestIndPower
from statsmodels.stats.proportion import (
    power_proportions_2indep,
    samplesize_proportions_2indep_onetail,
)

from liftlab.stats import power as pw

PROPORTION_CASES = [
    # baseline, mde, alpha, power, alternative
    (0.30, 0.05, 0.05, 0.80, "two-sided"),
    (0.30, 0.03, 0.05, 0.80, "two-sided"),
    (0.30, 0.02, 0.05, 0.90, "two-sided"),
    (0.05, 0.01, 0.05, 0.80, "two-sided"),
    (0.50, 0.10, 0.01, 0.80, "two-sided"),
    (0.80, -0.05, 0.05, 0.80, "two-sided"),
    (0.30, 0.05, 0.05, 0.80, "larger"),
    (0.60, -0.04, 0.10, 0.85, "smaller"),
]


@pytest.mark.parametrize(("baseline", "mde", "alpha", "power", "alternative"), PROPORTION_CASES)
def test_proportion_sample_size_is_the_smallest_n_statsmodels_says_is_enough(
    baseline, mde, alpha, power, alternative
):
    n = pw.sample_size_proportions(baseline, mde, alpha=alpha, power=power, alternative=alternative)

    def sm_power(nobs):
        return power_proportions_2indep(
            mde, baseline, nobs, alpha=alpha, alternative=alternative
        ).power

    assert sm_power(n) >= power > sm_power(n - 1)
    # statsmodels solves with one tail only; the other tail can save at most one user.
    one_tail = samplesize_proportions_2indep_onetail(
        mde, baseline, power, alpha=alpha, alternative=alternative
    )
    assert math.ceil(one_tail) - n in (0, 1)


@pytest.mark.parametrize(("baseline", "mde", "alpha", "power", "alternative"), PROPORTION_CASES)
def test_proportion_power_matches_statsmodels(baseline, mde, alpha, power, alternative):
    for n in (50, 800, 12_345):
        ours = pw.power_proportions(baseline, mde, n, alpha=alpha, alternative=alternative)
        theirs = power_proportions_2indep(mde, baseline, n, alpha=alpha, alternative=alternative)
        assert ours == pytest.approx(theirs.power, abs=1e-12)


@pytest.mark.parametrize(
    ("effect", "alpha", "power", "alternative"),
    [(0.2, 0.05, 0.80, "two-sided"), (0.1, 0.01, 0.80, "larger"), (0.05, 0.05, 0.90, "two-sided")],
)
def test_mean_sample_size_matches_statsmodels(effect, alpha, power, alternative):
    sd = 2.5
    n = pw.sample_size_means(
        4.0, sd, effect * sd, alpha=alpha, power=power, alternative=alternative
    )
    normal = NormalIndPower().solve_power(effect, alpha=alpha, power=power, alternative=alternative)
    assert n == math.ceil(normal)
    # A t-test needs a hair more; at these sizes it's at most one user.
    t_test = TTestIndPower().solve_power(effect, alpha=alpha, power=power, alternative=alternative)
    assert math.ceil(t_test) - n in (0, 1)
    assert pw.power_means(4.0, sd, effect * sd, n, alpha=alpha, alternative=alternative) == (
        pytest.approx(NormalIndPower().power(effect, n, alpha, alternative=alternative), abs=1e-12)
    )


def test_relative_mde_is_a_share_of_the_baseline():
    assert pw.sample_size_proportions(0.30, 0.10, relative=True) == pw.sample_size_proportions(
        0.30, 0.03
    )
    assert pw.sample_size_means(3.0, 2.0, 0.10, relative=True) == pw.sample_size_means(
        3.0, 2.0, 0.3
    )


@pytest.mark.parametrize("n", [200, 1377, 20_000])
def test_mde_is_the_inverse_of_sample_size(n):
    mde = pw.mde_proportions(0.30, n)
    assert pw.power_proportions(0.30, mde, n) == pytest.approx(0.80, abs=1e-9)
    assert pw.sample_size_proportions(0.30, mde) in (n, n + 1)
    assert pw.mde_proportions(0.30, n, relative=True) == pytest.approx(mde / 0.30)
    down = pw.mde_proportions(0.30, n, alternative="smaller")
    assert down < 0
    assert pw.power_proportions(0.30, down, n, alternative="smaller") == pytest.approx(0.80)

    mean_mde = pw.mde_means(3.0, 2.0, n)
    assert pw.power_means(3.0, 2.0, mean_mde, n) == pytest.approx(0.80, abs=1e-9)
    # With a known sd the inverse has a closed form, if the far tail is ignored.
    z = pw._Z.inv_cdf(0.975) + pw._Z.inv_cdf(0.80)
    assert mean_mde == pytest.approx(z * 2.0 * math.sqrt(2 / n), rel=1e-5)


def test_exp_001_plan():
    # Day 3's synthetic baseline (30.0%) and the pre-registered MDE of +5 points.
    n = pw.sample_size_proportions(0.30, 0.05)
    assert n == 1377
    assert pw.duration_days(n, 10) == 276
    assert pw.duration_days(n, 40) == 69


def test_duration_rounds_up_to_whole_days():
    assert pw.duration_days(100, 200) == 1
    assert pw.duration_days(100, 199) == 2
    assert pw.duration_days(100, 50, arms=3) == 6
    with pytest.raises(ValueError):
        pw.duration_days(100, 0)


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: pw.sample_size_proportions(1.2, 0.05), "baseline"),
        (lambda: pw.sample_size_proportions(0.98, 0.05), "0-1 range"),
        (lambda: pw.sample_size_proportions(0.30, 0), "zero"),
        (lambda: pw.sample_size_proportions(0.30, -0.05, alternative="larger"), "larger"),
        (lambda: pw.sample_size_proportions(0.30, 0.05, alpha=0), "alpha"),
        (lambda: pw.sample_size_proportions(0.30, 0.05, power=0.01), "power"),
        (lambda: pw.sample_size_proportions(0.30, 0.05, alternative="two"), "alternative"),
        (lambda: pw.sample_size_means(0, 1.0, 0.1, relative=True), "baseline"),
        (lambda: pw.sample_size_means(1.0, 0, 0.1), "sd"),
        (lambda: pw.mde_proportions(0.99, 5), "reaches"),
    ],
)
def test_rejects_impossible_plans(call, message):
    with pytest.raises(ValueError, match=message):
        call()
