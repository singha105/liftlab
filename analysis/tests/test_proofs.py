"""The simulation proofs at a handful of runs: the wiring, the known values they lean on, and
the properties that hold run by run. The headline rates need 1,000 runs and come from
`liftlab proofs`; they're in docs/STATS.md."""

import json
import math

import numpy as np
import pytest
from scipy import stats as sps
from statsmodels.stats.proportion import proportion_confint

from liftlab import cli, proof_charts, proofs


def test_constants_are_exp001s_plan():
    assert proofs.N_PER_ARM == 1377
    assert abs(proofs.MIXING_SD - 0.0620) < 5e-4


def test_srm_power_matches_the_normal_form():
    # df 1: the statistic is (Z + sqrt(noncentrality))^2, so power is two normal tails.
    critical = math.sqrt(sps.chi2.isf(0.001, 1))
    for total in (2754, 10_000, 20_000):
        shift = math.sqrt(total * 4 * 0.02**2)
        expected = sps.norm.sf(critical - shift) + sps.norm.cdf(-critical - shift)
        assert proofs.srm_power(total, 0.52) == pytest.approx(expected, rel=1e-6)
    assert proofs.srm_power(10_000, 0.50) == pytest.approx(0.001)  # the check's own alpha
    assert proofs.srm_power(2754, 0.52) == pytest.approx(0.12, abs=0.01)


@pytest.mark.parametrize(("k", "n"), [(0, 8), (49, 1000), (157, 200), (8, 8)])
def test_wilson_matches_statsmodels(k, n):
    assert proofs.wilson(k, n) == pytest.approx(proportion_confint(k, n, method="wilson"))


def test_fixed_horizon_proofs_count_what_they_report():
    aa, power = proofs.aa_test(4), proofs.power_check(4)
    assert aa.expected == proofs.ALPHA
    assert power.expected == pytest.approx(0.80, abs=0.02)  # at the simulator's true control
    for r in (aa, power):
        assert len(r.p_values) == len(r.diffs) == r.runs == 4
        assert r.detected == sum(p < proofs.ALPHA for p in r.p_values)
        assert r.rate_ci[0] <= r.rate <= r.rate_ci[1]
    assert power.mean_diff > aa.mean_diff


def test_peeking_msprt_never_stops_where_the_z_test_would_not():
    # 1/Lambda <= 0.05 needs |z| >= 3.0 at that look for any mixing sd (test_stats_methods),
    # so every mSPRT rejection is also a fixed-horizon rejection on the same day.
    r = proofs.peeking(3)
    naive, msprt = np.array(r.naive_by_day), np.array(r.msprt_by_day)
    assert len(naive) == len(msprt) == proofs.PEEK_DAYS
    assert np.all(np.diff(naive) >= 0) and np.all(np.diff(msprt) >= 0)
    assert np.all(msprt <= naive)
    assert r.naive_rate == naive[-1] and r.msprt_rate == msprt[-1]
    # About EXP-001's N per arm has arrived by the last look.
    assert 0.7 * proofs.N_PER_ARM < r.mean_users_per_arm < 1.5 * proofs.N_PER_ARM


def test_cuped_run_reduces_the_standard_error():
    raw, raw_se, adj, adj_se, n, *returning = proofs.cuped_run(proofs.FIRST_SEED["cuped"])
    assert adj_se < raw_se
    assert abs(adj - raw) < 2 * raw_se  # same target, slightly different noise
    assert returning[4] < n


def test_srm_run_flags_a_large_skew_and_not_a_fair_split():
    exposed, p_skewed = proofs.srm_run(proofs.FIRST_SEED["srm"], 20_000, 0.52)
    assert exposed == pytest.approx(20_000, rel=0.02)
    assert p_skewed < 0.001
    _, p_fair = proofs.srm_run(proofs.FIRST_SEED["srm"], 2754, 0.50)
    assert p_fair > 0.001


def _fake_results() -> dict[str, object]:
    rng = np.random.default_rng(0)
    p, diffs = rng.uniform(size=60).tolist(), rng.normal(0.05, 0.018, 60).tolist()
    by_day = np.linspace(0.01, 0.25, proofs.PEEK_DAYS)
    fixed = dict(detected=3, rate=0.05, rate_ci=(0.02, 0.14), mean_diff=0.0, p_values=p)
    return {
        "aa": proofs.FixedHorizon(runs=60, true_effect=0.0, expected=0.05, diffs=diffs, **fixed),
        "peeking": proofs.Peeking(
            runs=60, looks=proofs.PEEK_DAYS, naive_rate=0.25, naive_ci=(0.16, 0.37),
            msprt_rate=0.02, msprt_ci=(0.01, 0.1), single_look_rate=0.05, mixing_sd=0.062,
            naive_by_day=by_day.tolist(), msprt_by_day=(by_day / 10).tolist(),
            mean_users_per_arm=1400.0,
        ),
        "cuped": proofs.CupedProof(
            runs=60, mean_users=7000.0, variance_reduction=0.2,
            empirical_variance_reduction=0.2, ci_width_reduction=0.1, coverage_raw=0.95,
            coverage_cuped=0.95, returning_variance_reduction=0.1, returning_mean_users=3000.0,
            raw_estimates=diffs, cuped_estimates=[d * 0.9 for d in diffs],
        ),
        "srm": proofs.SRMProof(
            runs=60, sizes=[2744, 9961, 19920],
            flagged={"50%": [0.0, 0.0, 0.017], "52%": [0.12, 0.75, 0.98]},
            expected_52=[0.12, 0.76, 0.99],
        ),
        "power": proofs.FixedHorizon(runs=60, true_effect=0.05, expected=0.8, diffs=diffs, **fixed),
    }  # fmt: skip


def test_charts_render_light_and_dark(tmp_path):
    written = proof_charts.save_all(_fake_results(), tmp_path)
    assert len(written) == 10
    assert {path.name for path in written} >= {"stats-peeking-light.png", "stats-srm-dark.png"}
    assert all(path.stat().st_size > 10_000 for path in written)


def test_cli_proofs_writes_charts_and_summary(tmp_path, capsys):
    args = ["proofs", "--runs", "3", "--only", "aa", "--workers", "1"]
    assert cli.main([*args, "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.count("SYNTHETIC") == 2
    assert "A/A false-positive rate" in out
    summary = json.loads((tmp_path / "stats-proofs.json").read_text())
    assert summary["label"].startswith("SYNTHETIC")
    assert summary["aa"]["runs"] == 3 and len(summary["aa"]["p_values"]) == 3
    assert sorted(path.name for path in tmp_path.glob("*.png")) == [
        "stats-aa-pvalues-dark.png",
        "stats-aa-pvalues-light.png",
    ]
