import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from conftest import build_warehouse, event

from liftlab import cli, readout, warehouse
from liftlab.readout import SYNTHETIC_LABEL, at_required_n, build_readout, load_config, population
from liftlab.simulate import Experiment, simulate
from liftlab.stats import power as pw
from liftlab.stats.bootstrap import bootstrap_ci
from liftlab.stats.tests import ratio_metric, welch_ttest, ztest_proportions

CONFIG = load_config(cli.EXP_001_CONFIG)
START = datetime(2026, 11, 2)


def _config(**changes) -> dict:
    return {**CONFIG, **changes}


def _users(
    n=(1500, 1500),
    activation=(0.30, 0.30),
    sessions=(1.4, 1.4),
    abandon=(0.30, 0.30),
    load=(700.0, 700.0),
    seed=0,
    source="synthetic",
) -> pd.DataFrame:
    """Exposed users with known rates: activation and abandon counts are exact."""
    rng = np.random.default_rng(seed)
    frames = []
    for arm, size, act, mean, ab, ms in zip(
        ("control", "test"), n, activation, sessions, abandon, load, strict=True
    ):
        activated = np.arange(size) < round(act * size)
        abandoned = np.zeros(size, dtype=int)
        abandoned[: round(ab * size)] = 1
        frames.append(
            pd.DataFrame(
                {
                    "source": source,
                    "experiment_key": "exp-001",
                    "user_id": [f"{arm}-{i}" for i in range(size)],
                    "variant": arm,
                    "variants": 1,
                    "exposed_at": [
                        START + timedelta(minutes=2 * i + (arm == "test")) for i in range(size)
                    ],
                    "new_at_exposure": True,
                    "activation_window_closed": True,
                    "activated": rng.permutation(activated),
                    "completed_sessions_7d": rng.poisson(mean, size),
                    "abandoned_sessions_7d": abandoned,
                    "ended_sessions_7d": np.ones(size, dtype=int),  # so the rate is exact
                    "device_type": rng.choice(["Desktop", "Mobile"], size),
                    "referrer_type": rng.choice(["direct", "search", "social"], size),
                    "load_ms_7d": [list(rng.lognormal(np.log(ms), 0.3, 2)) for _ in range(size)],
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def test_config_is_the_preregistered_plan():
    assert CONFIG["key"] == "exp-001"
    assert CONFIG["required_per_arm"] == 1377
    assert CONFIG["primary"]["mde"] == 0.05
    assert [r["decision"] for r in CONFIG["decision_rule"]] == [
        "INVALID", "UNDERPOWERED", "KILL", "SHIP", "ITERATE", "KILL",
    ]  # fmt: skip
    assert CONFIG["guardrails"][0]["max_increase"] == 0.02
    assert CONFIG["guardrails"][1]["max_relative_increase"] == 0.10


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"arms": {"a": 0.5, "b": 0.5}}, "arms"),
        ({"decision_rule": [{"decision": "MAYBE", "when": ["otherwise"]}]}, "unknown decision"),
        ({"decision_rule": [{"decision": "SHIP", "when": ["vibes"]}]}, "unknown condition"),
    ],
)
def test_bad_configs_are_rejected(change, message):
    with pytest.raises(ValueError, match=message):
        build_readout(_users(), _config(**change))


def test_numbers_come_from_the_stats_library():
    users = _users(activation=(0.30, 0.34), sessions=(1.4, 1.5), abandon=(0.3, 0.31), seed=1)
    r = build_readout(users, CONFIG)
    c, t = users[users.variant == "control"], users[users.variant == "test"]
    assert r.primary.comparison == ztest_proportions(
        int(c.activated.sum()), len(c), int(t.activated.sum()), len(t)
    )
    assert r.secondaries[0].comparison == welch_ttest(
        c.completed_sessions_7d.astype(float), t.completed_sessions_7d.astype(float)
    )
    abandon = ratio_metric(
        c.abandoned_sessions_7d, c.ended_sessions_7d, t.abandoned_sessions_7d, t.ended_sessions_7d
    )
    assert r.guardrails[0].diff == pytest.approx(abandon.diff)
    assert r.guardrails[0].ci == pytest.approx(abandon.ci)
    assert r.secondaries[0].holm_p == pytest.approx(r.secondaries[0].comparison.p_value)


@pytest.mark.parametrize(
    ("kwargs", "decision", "reason"),
    [
        ({"n": (1500, 1800)}, "INVALID", "sample ratio mismatch"),
        ({"n": (1300, 1300)}, "UNDERPOWERED", "short of the required 1,377"),
        ({"activation": (0.30, 0.40), "abandon": (0.30, 0.34)}, "KILL", "Abandon rate regressed"),
        ({"activation": (0.30, 0.40), "load": (700, 820)}, "KILL", "Page load p75 regressed"),
        ({"activation": (0.30, 0.40), "load": (1900, 2000)}, "KILL", "cap of 2,000 ms"),
        ({"activation": (0.30, 0.36)}, "SHIP", "entirely above 0"),
        ({"activation": (0.30, 0.33)}, "ITERATE", "at least half the MDE"),
        ({"activation": (0.30, 0.36), "sessions": (1.4, 1.1)}, "ITERATE", "significantly worse"),
        ({"activation": (0.30, 0.31)}, "KILL", "below half the MDE"),
    ],
)
def test_each_branch_of_the_decision_rule(kwargs, decision, reason):
    r = build_readout(_users(**kwargs), CONFIG)
    assert r.decision == decision
    assert reason in " ".join(r.reasons)


def test_users_in_both_arms_are_dropped_and_counted():
    users = _users()
    users.loc[:9, "variants"] = 2
    r = build_readout(users, CONFIG)
    assert r.dropped_multiple_arms == 10
    assert r.users == {"control": 1490, "test": 1500}


def test_population_and_read_at_required_n():
    users = _users(n=(2000, 2000))
    users.loc[users.index[::10], "new_at_exposure"] = False
    analyzed = at_required_n(population(users, CONFIG), CONFIG)
    assert analyzed.new_at_exposure.all()
    counts = analyzed.variant.value_counts()
    assert min(counts) == 1377
    # The read stops on the user who fills the smaller arm.
    last = analyzed.iloc[-1]
    assert counts[last.variant] == 1377


def test_adjustment_is_reported_but_never_decides():
    users = _users(activation=(0.30, 0.36))
    r = build_readout(users, CONFIG)
    assert r.adjusted is not None
    assert r.adjusted.unadjusted_estimate == pytest.approx(r.primary.comparison.diff)
    assert "sensitivity only" in r.adjusted_label


def test_markdown_and_json_are_labelled_synthetic():
    r = build_readout(_users(activation=(0.30, 0.33)), CONFIG)
    markdown = r.to_markdown()
    assert markdown.startswith("# EXP-001 Quick Start: ITERATE")
    assert markdown.count(SYNTHETIC_LABEL) == 2
    data = json.loads(r.to_json())
    assert data["decision"] == "ITERATE"
    assert data["label"] == SYNTHETIC_LABEL
    assert data["srm"]["mismatch"] is False


def test_real_readouts_are_labelled_with_their_n():
    real = build_readout(_users(activation=(0.30, 0.33), source="posthog"), CONFIG)
    label = "REAL: StudySprint live data, N = 3,000"
    assert real.label == label and not real.synthetic
    assert SYNTHETIC_LABEL not in real.to_markdown()
    assert real.to_markdown().count(label) == 2
    assert json.loads(real.to_json())["label"] == label

    small = build_readout(_users(n=(20, 17), source="posthog"), CONFIG)
    assert small.decision == "UNDERPOWERED"
    assert small.label == "REAL: StudySprint live data, N = 37, underpowered (needs 1,377 per arm)"
    mixed = pd.concat([_users(n=(5, 5)), _users(n=(5, 5), source="posthog")], ignore_index=True)
    assert build_readout(mixed, CONFIG).label.startswith("REAL: None data")
    named = build_readout(_users(source="csv"), _config(label="REAL: a public test"))
    assert named.label == "REAL: a public test, N = 3,000"


def test_bootstrap_statistics_and_proportion_guardrails():
    users = _users(activation=(0.30, 0.34), sessions=(1.4, 1.6), seed=2)
    users["never_started"] = users.index % 10 == 0
    primary = {**CONFIG["primary"], "bootstrap": ["mean"]}
    secondary = [{**CONFIG["secondary"][0], "bootstrap": ["mean", "median"]}]
    guardrail = {"name": "Never started", "type": "proportion", "column": "never_started",
                 "max_increase": 0.01}  # fmt: skip
    config = _config(
        primary=primary,
        secondary=secondary,
        guardrails=[guardrail],
        bootstrap_resamples=500,
        actions={"SHIP": "make Quick Start the default"},
    )
    r = build_readout(users, config)
    c, t = users[users.variant == "control"], users[users.variant == "test"]

    (rate,) = r.primary.bootstraps
    expected = bootstrap_ci(
        lambda a, b: b.mean(axis=1) - a.mean(axis=1),
        c.activated.to_numpy(float),
        t.activated.to_numpy(float),
        n_resamples=500,
        seed=0,
    )
    assert rate.diff == expected
    assert (rate.control, rate.test) == pytest.approx((c.activated.mean(), t.activated.mean()))
    # The bootstrap and the Wald interval agree for a rate this far from 0 and 1.
    assert rate.diff.ci == pytest.approx(r.primary.comparison.ci, abs=0.006)

    mean, median = r.secondaries[0].bootstraps
    assert mean.diff.estimate == pytest.approx(r.secondaries[0].comparison.diff)
    sessions = (c.completed_sessions_7d.median(), t.completed_sessions_7d.median())
    assert (median.control, median.test) == sessions
    assert median.diff.estimate == sessions[1] - sessions[0]

    (never,) = r.guardrails
    flat = ztest_proportions(int(c.never_started.sum()), len(c), int(t.never_started.sum()), len(t))
    assert (never.diff, never.ci, never.regressed) == (flat.diff, flat.ci, False)

    markdown = r.to_markdown()
    assert f"Bootstrap, difference in medians: {sessions[0]:.2f} → {sessions[1]:.2f}" in markdown
    assert "(500 resamples of users)" in markdown
    assert "Guardrail, Never started" in markdown and "(threshold +1.0pp) ok" in markdown
    assert r.decision == "SHIP" and r.action == "make Quick Start the default"
    assert "**Decision: SHIP, make Quick Start the default**" in markdown

    with pytest.raises(ValueError, match="bootstrap statistics"):
        build_readout(users, _config(primary={**primary, "bootstrap": ["p90"]}))


def test_interim_reads_any_n_and_decides_nothing():
    none = readout.interim(_users(n=(0, 0), source="posthog"), CONFIG, "posthog")
    assert none.users == {"control": 0, "test": 0}
    assert none.label == "REAL: StudySprint live data, N = 0, underpowered (needs 1,377 per arm)"
    assert (none.power_at_mde, none.mde_at_n, none.readout) == (None, None, None)
    assert "with no users the test can't detect +5.0pp" in none.to_markdown()

    small = readout.interim(_users(n=(20, 17), source="posthog"), CONFIG)
    assert small.power_at_mde == pytest.approx(pw.power_proportions(0.30, 0.05, 17))
    assert small.mde_at_n == pytest.approx(pw.mde_proportions(0.30, 17))
    assert small.readout is not None and small.readout.decision == "UNDERPOWERED"
    text = small.to_markdown()
    assert text.count(small.label) == 2 and "N = 37, underpowered" in small.label
    assert "## The read so far" in text and "**Decision: UNDERPOWERED**" in text

    # EXP-001.md: at the 8-week cap, about 140 per arm, it can only detect about 16 points.
    capped = readout.interim(_users(n=(140, 140), source="posthog"), CONFIG)
    assert capped.mde_at_n == pytest.approx(0.162, abs=0.001)
    assert capped.power_at_mde == pytest.approx(0.145, abs=0.001)
    synthetic = readout.interim(_users(n=(1500, 1500)), CONFIG)
    assert synthetic.label == SYNTHETIC_LABEL


# The experiment_users model


@pytest.fixture(scope="module")
def experiment_run():
    sim = simulate(
        8000,
        seed=3,
        weeks=6,
        experiment=Experiment(start_day=28, audience="all", sessions_effect=0.2, srm_loss=0.05),
    )
    con = warehouse.connect(":memory:")
    warehouse.load_events(con, sim.events, source="synthetic", data_end=sim.truth.data_end)
    warehouse.build(con)
    return sim, readout.experiment_users(con, "exp-001", "synthetic")


def test_experiment_users_match_simulator_truth(experiment_run):
    sim, users = experiment_run
    truth = sim.users[sim.users.variant.notna() & ~sim.users.is_demo & sim.users.exposure_logged]
    merged = users.merge(truth, left_on="user_id", right_on="distinct_id", how="outer")
    assert len(merged) == len(users) == len(truth)
    assert (merged.variant_x == merged.variant_y).all()
    assert (merged.new_at_exposure_x == merged.new_at_exposure_y).all()
    assert (merged.pre_sessions_28d == merged.pre_sessions).all()
    assert (users.variants == 1).all()


def test_experiment_users_session_counts_add_up(experiment_run):
    _, users = experiment_run
    assert (
        users.ended_sessions_7d == users.completed_sessions_7d + users.abandoned_sessions_7d
    ).all()
    assert (users.ended_sessions_7d <= users.started_sessions_7d).all()
    closed = users[users.window_7d_closed]
    # Every session started in a closed window has an outcome.
    assert (closed.ended_sessions_7d == closed.started_sessions_7d).all()


def test_experiment_users_edge_cases():
    con = build_warehouse(
        [
            event(
                "u1",
                "app_opened",
                "2026-11-02T09:00:00",
                is_first_open=True,
                load_ms=900,
                referrer_type="search",
                **{"$device_type": "Mobile"},
            ),
            event(
                "u1",
                "experiment_exposed",
                "2026-11-02T09:00:01",
                experiment_key="exp-001",
                variant="test",
            ),
            # Completed, abandoned, and no end event after 24 hours: abandoned.
            event("u1", "session_started", "2026-11-02T09:01:00", session_id="s1"),
            event("u1", "session_completed", "2026-11-02T09:26:00", session_id="s1"),
            event("u1", "session_started", "2026-11-04T10:00:00", session_id="s2"),
            event(
                "u1",
                "session_abandoned",
                "2026-11-04T10:05:00",
                session_id="s2",
                reason="user_ended",
                elapsed_seconds=300,
            ),
            event("u1", "app_opened", "2026-11-05T08:00:00", load_ms=1200),
            event("u1", "session_started", "2026-11-05T08:01:00", session_id="s3"),
            # Day 8: outside the window, for sessions and loads.
            event("u1", "app_opened", "2026-11-10T08:00:00", load_ms=5000),
            event("u1", "session_started", "2026-11-10T08:01:00", session_id="s4"),
            # Exposed on a later visit, then seen in the other arm too.
            event("u2", "app_opened", "2026-11-01T09:00:00", is_first_open=True, load_ms=700),
            event("u2", "session_started", "2026-11-01T09:01:00", session_id="s5"),
            event("u2", "app_opened", "2026-11-03T09:00:00", load_ms=650),
            event(
                "u2",
                "experiment_exposed",
                "2026-11-03T09:00:01",
                experiment_key="exp-001",
                variant="control",
            ),
            event(
                "u2",
                "experiment_exposed",
                "2026-11-04T09:00:01",
                experiment_key="exp-001",
                variant="test",
            ),
        ],  # fmt: skip
        data_end="2026-11-12T00:00:00",
    )
    rows = readout.experiment_users(con, "exp-001", "synthetic").set_index("user_id")
    u1, u2 = rows.loc["u1"], rows.loc["u2"]
    assert (u1.variant, u1.variants, bool(u1.new_at_exposure)) == ("test", 1, True)
    assert (u1.device_type, u1.referrer_type) == ("Mobile", "search")
    assert (u1.started_sessions_7d, u1.completed_sessions_7d, u1.abandoned_sessions_7d) == (3, 1, 2)
    assert u1.ended_sessions_7d == 3
    assert bool(u1.activated)
    assert list(u1.load_ms_7d) == [1200]  # not the exposure load, not day 8
    assert (u2.variant, u2.variants, bool(u2.new_at_exposure)) == ("control", 2, False)
    assert u2.pre_sessions_28d == 1
    assert bool(u2.window_7d_closed)


def test_cli_readout(tmp_path, capsys):
    db = str(tmp_path / "warehouse.duckdb")
    simulate_exp_001 = ["--users", "3581", "--weeks", "2", "--seed", "4", "--experiment",
                        "exp-001", "--experiment-start-day", "0", "--audience", "new",
                        "--activation-effect", "0.05"]  # fmt: skip
    assert cli.main(["--db", db, "load", "--source", "synthetic", *simulate_exp_001]) == 0
    assert cli.main(["--db", db, "build"]) == 0
    out = tmp_path / "readout.json"
    args = ["--db", db, "readout", "--source", "synthetic", "--format", "json", "--out", str(out)]
    assert cli.main(args) == 0
    data = json.loads(out.read_text())
    assert data["label"] == SYNTHETIC_LABEL
    assert min(data["users"].values()) == 1377
    assert cli.main(["--db", db, "readout", "--source", "posthog"]) == 1
    err = capsys.readouterr().err
    assert "No users exposed to exp-001" in err
    assert "REAL: StudySprint live data, N = 0, underpowered" in err
    assert cli.main(["--db", db, "readout", "--source", "posthog", "--interim"]) == 0
    assert "EXP-001 Quick Start: interim read, not a decision" in capsys.readouterr().out
