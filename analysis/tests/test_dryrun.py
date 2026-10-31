import pytest
from statsmodels.stats.proportion import proportion_confint

from liftlab import cli, dryrun
from liftlab.dryrun import PowerCheck, Run
from liftlab.stats.tests import ztest_proportions


def test_a_run_reads_the_warehouse_and_stops_when_both_arms_are_full():
    run = dryrun.run_once(3, n_per_arm=300, effect=0.15)
    assert run.true_effect == pytest.approx(0.15)
    assert run.true_control == pytest.approx(0.3069, abs=1e-4)
    # It stops on the user who fills the smaller arm, like the real read at N per arm.
    assert min(run.result.n_control, run.result.n_test) == 300
    assert run.detected


def _fake_check(detected: int, reps: int) -> PowerCheck:
    result = ztest_proportions(30, 100, 40, 100)
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
