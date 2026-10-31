import pytest
from statsmodels.stats.proportion import (
    confint_proportions_2indep,
    proportion_confint,
    proportions_ztest,
)

from liftlab import cli, dryrun
from liftlab.dryrun import PowerCheck, Run, two_proportion_ztest


@pytest.mark.parametrize(
    ("x_c", "n_c", "x_t", "n_t"), [(413, 1377, 482, 1377), (90, 300, 70, 310), (5, 40, 9, 41)]
)
def test_ztest_matches_statsmodels(x_c, n_c, x_t, n_t):
    ours = two_proportion_ztest(x_c, n_c, x_t, n_t)
    z, p = proportions_ztest([x_t, x_c], [n_t, n_c])
    low, high = confint_proportions_2indep(x_t, n_t, x_c, n_c, method="wald")
    assert ours.z == pytest.approx(z)
    assert ours.p_value == pytest.approx(p)
    assert (ours.ci_low, ours.ci_high) == pytest.approx((low, high))
    assert ours.diff == pytest.approx(x_t / n_t - x_c / n_c)


def test_a_run_reads_the_warehouse_and_stops_when_both_arms_are_full():
    run = dryrun.run_once(3, n_per_arm=300, effect=0.15)
    assert run.true_effect == pytest.approx(0.15)
    assert run.true_control == pytest.approx(0.3069, abs=1e-4)
    # It stops on the user who fills the smaller arm, like the real read at N per arm.
    assert min(run.result.n_control, run.result.n_test) == 300
    assert run.detected


def _fake_check(detected: int, reps: int) -> PowerCheck:
    result = two_proportion_ztest(30, 100, 40, 100)
    return PowerCheck([Run(i, 0.3, 0.05, result, i < detected) for i in range(reps)])


def test_power_interval_is_wilson():
    check = _fake_check(161, 200)
    assert check.power == pytest.approx(0.805)
    assert check.power_ci() == pytest.approx(proportion_confint(161, 200, method="wilson"))


def test_cli_dry_run_is_labelled_synthetic(capsys):
    assert cli.main(["dry-run", "--reps", "2", "--mde", "0.15"]) == 0
    out = capsys.readouterr().out
    assert out.count("SYNTHETIC") == 2
    assert "2 runs in" in out
    assert "Run 1 (seed 1)" in out
