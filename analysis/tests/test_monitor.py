from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from liftlab import cli, monitor
from liftlab.readout import SYNTHETIC_LABEL, load_config
from liftlab.stats.sequential import msprt
from liftlab.stats.tests import ratio_metric

CONFIG = load_config(cli.EXP_001_CONFIG)
LAUNCH = datetime(2026, 11, 2)
SIX_WEEKS = LAUNCH + timedelta(weeks=6)


def _users(per_week=(400, 400), abandon=(0.30, 0.30), load=(700.0, 700.0), weeks=6, seed=0):
    """Exposures spread evenly over `weeks`, abandons spread evenly among them."""
    rng = np.random.default_rng(seed)
    frames = []
    for arm, size, ab, ms in zip(("control", "test"), per_week, abandon, load, strict=True):
        n, k = size * weeks, np.arange(size * weeks)
        abandoned = np.floor((k + 1) * ab) > np.floor(k * ab)  # evenly spread, exact rate
        frames.append(
            pd.DataFrame(
                {
                    "source": "synthetic",
                    "user_id": [f"{arm}-{i}" for i in range(n)],
                    "variant": arm,
                    "variants": 1,
                    "exposed_at": [
                        LAUNCH + timedelta(weeks=weeks) * (i + 0.5) / n for i in range(n)
                    ],
                    "new_at_exposure": True,
                    "activation_window_closed": True,
                    "abandoned_sessions_7d": abandoned.astype(int),
                    "ended_sessions_7d": 1,
                    "load_ms_7d": [list(rng.lognormal(np.log(ms), 0.3, 2)) for _ in range(n)],
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def test_no_change_continues_with_a_look_a_week():
    m = monitor.weekly_checks(_users(), CONFIG, SIX_WEEKS)
    assert m.status == "CONTINUE"
    assert [look.week for look in m.looks] == [1, 2, 3, 4, 5, 6]
    assert m.looks[0].guardrail_users == {"control": 0, "test": 0}
    assert [b.measure for b in m.bounds] == ["test - control", "test / control - 1", "test arm"]
    for b in m.bounds:
        assert np.isnan(b.estimates[0])
        assert all(np.diff(b.ci_low[1:]) >= 0) and all(np.diff(b.ci_high[1:]) <= 0)
    abandon, relative, _ = m.bounds
    assert abandon.ci_low[-1] < 0 < abandon.ci_high[-1]
    assert relative.ci_low[-1] < 0 < relative.ci_high[-1]


def test_only_users_with_a_closed_window_count_for_guardrails():
    users = _users()
    m = monitor.weekly_checks(users, CONFIG, SIX_WEEKS)
    for look in m.looks:
        closed = users[users["exposed_at"] + timedelta(days=8) <= look.at]
        exposed = users[users["exposed_at"] <= look.at]
        assert sum(look.guardrail_users.values()) == len(closed)
        assert sum(look.users.values()) == len(exposed)


def test_bounds_are_the_msprt_of_each_weeks_estimate():
    users = _users(abandon=(0.30, 0.33))
    m = monitor.weekly_checks(users, CONFIG, SIX_WEEKS)
    estimates, variances = [], []
    for look in m.looks[1:]:
        closed = users[users["exposed_at"] + timedelta(days=8) <= look.at]
        arm = (closed["variant"] == "test").to_numpy()
        y, x = closed["abandoned_sessions_7d"].to_numpy(float), np.ones(len(closed))
        r = ratio_metric(y[~arm], x[~arm], y[arm], x[arm])
        estimates.append(r.diff)
        variances.append(r.se**2)
    expected = msprt(estimates, variances, mixing_sd=0.02)
    abandon = m.bounds[0]
    assert abandon.mixing_sd == 0.02
    assert abandon.estimates[1:] == pytest.approx(estimates)
    assert abandon.ci_low[1:] == pytest.approx(expected.ci_low)
    assert abandon.ci_high[1:] == pytest.approx(expected.ci_high)


def test_a_large_abandon_regression_stops_the_run():
    m = monitor.weekly_checks(_users(abandon=(0.30, 0.50)), CONFIG, SIX_WEEKS)
    assert m.status == "KILL"
    stop = len(m.looks) - 1
    assert stop < 5  # well before the last look
    assert m.bounds[0].ci_low[stop] > 0.02
    assert all(len(b.estimates) == len(m.looks) for b in m.bounds)
    assert "Abandon rate" in m.reasons[0] and "always-valid" in m.reasons[0]


def test_a_regression_just_past_the_threshold_waits_for_the_read():
    # +3 points is past the +2-point limit, so the read would say KILL; the weekly check
    # needs its always-valid interval past the limit too.
    m = monitor.weekly_checks(_users(abandon=(0.30, 0.33)), CONFIG, SIX_WEEKS)
    assert m.status == "CONTINUE"
    assert m.bounds[0].estimates[-1] == pytest.approx(0.03, abs=0.005)


@pytest.mark.parametrize(
    ("load", "measure"), [((700.0, 1100.0), "test / control - 1"), ((3000.0, 3000.0), "test arm")]
)
def test_page_load_regressions_stop_the_run(load, measure):
    m = monitor.weekly_checks(_users(load=load), CONFIG, SIX_WEEKS)
    assert m.status == "KILL"
    crossed = [b.measure for b in m.bounds if b.crossed(len(m.looks) - 1)]
    assert crossed == [measure]


def test_sample_ratio_mismatch_stops_the_run():
    m = monitor.weekly_checks(_users(per_week=(400, 320)), CONFIG, SIX_WEEKS)
    assert m.status == "INVALID"
    assert m.looks[-1].srm_failed and not any(look.srm_failed for look in m.looks[:-1])
    assert m.reasons[0].startswith(f"week {m.looks[-1].week}: sample ratio mismatch")


def test_users_in_both_arms_are_left_out():
    users = _users()
    users.loc[users.index[:50], "variants"] = 2
    m = monitor.weekly_checks(users, CONFIG, SIX_WEEKS)
    assert sum(m.looks[-1].users.values()) == len(users) - 50


def test_before_the_first_full_week():
    m = monitor.weekly_checks(_users(), CONFIG, LAUNCH + timedelta(days=5))
    assert m.status == "CONTINUE" and m.looks == ()
    assert "no full week" in m.reasons[0]
    assert "# EXP-001 Quick Start: weekly check, CONTINUE" in m.to_markdown()


def test_launch_from_the_config():
    m = monitor.weekly_checks(_users(), {**CONFIG, "launch": "2026-11-05"}, SIX_WEEKS)
    assert m.launch == datetime(2026, 11, 5)
    assert len(m.looks) == 5


def test_markdown_and_json_are_labeled():
    m = monitor.weekly_checks(_users(abandon=(0.30, 0.50)), CONFIG, SIX_WEEKS)
    text = m.to_markdown()
    assert text.count(SYNTHETIC_LABEL) == 2
    assert "STOP, KILL" in text and "| Week |" in text
    assert m.to_dict()["label"] == SYNTHETIC_LABEL
    assert '"status": "KILL"' in m.to_json()

    users = _users(per_week=(10, 10))
    users["source"] = "posthog"
    real = monitor.weekly_checks(users, CONFIG, LAUNCH + timedelta(weeks=3))
    label = "REAL: StudySprint live data, N = 60, underpowered (needs 1,377 per arm)"
    assert real.label == label and real.to_markdown().count(label) == 2


def test_cli_monitor(tmp_path, capsys):
    db = str(tmp_path / "warehouse.duckdb")
    simulate_exp_001 = ["--users", "3000", "--weeks", "3", "--seed", "5", "--experiment",
                        "exp-001", "--experiment-start-day", "0", "--audience", "new"]  # fmt: skip
    assert cli.main(["--db", db, "load", "--source", "synthetic", *simulate_exp_001]) == 0
    assert cli.main(["--db", db, "build"]) == 0
    capsys.readouterr()
    assert cli.main(["--db", db, "monitor", "--source", "synthetic"]) == 0
    out = capsys.readouterr().out
    assert out.count(SYNTHETIC_LABEL) == 2
    assert "| 3 |" in out
    as_of = ["--as-of", "2026-09-10T00:00:00+00:00", "--format", "json"]
    assert cli.main(["--db", db, "monitor", "--source", "synthetic", *as_of]) == 0
    assert '"as_of": "2026-09-10 00:00:00"' in capsys.readouterr().out
    assert cli.main(["--db", db, "monitor", "--source", "posthog"]) == 1
