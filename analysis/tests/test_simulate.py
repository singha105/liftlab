import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from liftlab.simulate import Experiment, simulate

PLAN = Path(__file__).resolve().parents[2] / "docs" / "TRACKING_PLAN.md"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _section(title: str) -> str:
    text = PLAN.read_text()
    start = text.index(f"\n## {title}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else None]


def tracking_plan() -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    events = {}
    for line in _section("Events").splitlines():
        row = re.match(r"^\| `([a-z_]+)` \|[^|]*\|([^|]*)\|", line)
        if row:
            events[row[1]] = dict(re.findall(r"`([a-z_]+):([^`]+)`", row[2]))
    supers = {}
    for line in _section("Properties on every event").splitlines():
        row = re.match(r"^\| `([a-z_]+)` \| ([^|]+?) \|", line)
        if row:
            supers[row[1]] = row[2]
    return events, supers


def matches(value, spec: str) -> bool:
    if spec == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if spec == "bool":
        return isinstance(value, bool)
    if spec == "string":
        return isinstance(value, str)
    if spec == "uuid":
        return isinstance(value, str) and bool(UUID.match(value))
    options = spec.removeprefix("enum(").removesuffix(")").split(", ")
    return str(value) in options


def test_same_seed_same_events_and_truth():
    first, second = simulate(3_000, seed=3), simulate(3_000, seed=3)
    pd.testing.assert_frame_equal(first.events, second.events)
    pd.testing.assert_frame_equal(first.users, second.users)
    assert first.truth.as_rows() == second.truth.as_rows()
    assert not first.events.equals(simulate(3_000, seed=4).events)


def test_twenty_thousand_users_in_under_30_seconds(synthetic):
    _, _, elapsed = synthetic
    assert elapsed < 30


def test_events_follow_the_tracking_plan_exactly(synthetic):
    sim, _, _ = synthetic
    planned, supers = tracking_plan()
    sample = sim.events.sample(20_000, random_state=1)
    assert set(sim.events["event"]) <= set(planned)
    for name, raw in zip(sample["event"], sample["properties"], strict=True):
        props = {k: v for k, v in json.loads(raw).items() if not k.startswith("$")}
        expected = {**planned[name], **supers}
        assert set(props) == set(expected), name
        for key, value in props.items():
            assert matches(value, expected[key]), (name, key, value)


def test_events_look_like_a_posthog_export(synthetic):
    sim, _, _ = synthetic
    assert list(sim.events.columns) == ["uuid", "event", "distinct_id", "timestamp", "properties"]
    assert sim.events["timestamp"].is_monotonic_increasing
    assert sim.events["timestamp"].max() < pd.Timestamp(sim.truth.data_end)
    props = json.loads(sim.events["properties"].iloc[0])
    assert props["$current_url"] == "https://singha105.github.io/liftlab/"
    duplicated = sim.events["uuid"].duplicated().mean()
    assert 0 < duplicated < 0.01  # a few deliveries arrive twice, as in real exports


def test_truth_lands_on_the_backlog_baselines(synthetic):
    truth = synthetic[0].truth
    assert truth.start_rate == pytest.approx(0.50, abs=0.02)
    assert truth.activation_rate == pytest.approx(0.30, abs=0.02)
    assert truth.retention_curve[7] == pytest.approx(0.15, abs=0.02)
    curve = [truth.retention_curve[n] for n in (7, 14, 21, 28)]
    assert curve == sorted(curve, reverse=True)


@pytest.fixture(scope="module")
def experiment():
    config = Experiment(start_day=21, activation_effect=0.05, sessions_effect=0.2, srm_loss=0.1)
    return simulate(20_000, seed=11, experiment=config)


def test_experiment_truth_hits_the_configured_effects(experiment):
    truth = experiment.truth.experiment
    assert truth.activation_effect == pytest.approx(0.05, abs=1e-9)
    assert truth.activation_test == pytest.approx(truth.activation_control + 0.05, abs=1e-9)
    assert truth.sessions_lift == 0.2
    assert truth.start_shift > 0


def test_new_users_activation_effect_shows_up_in_the_sample(experiment):
    users = experiment.users
    new = users[users.new_at_exposure & ~users.is_demo]
    rates = new.groupby("variant")["activated"].agg(["mean", "count"])
    diff = rates.loc["test", "mean"] - rates.loc["control", "mean"]
    p = rates["mean"].mean()
    se = np.sqrt(p * (1 - p) * (1 / rates.loc["test", "count"] + 1 / rates.loc["control", "count"]))
    assert abs(diff - 0.05) < 4 * se


def test_returning_users_sessions_scale_by_the_lift(experiment):
    sim = experiment
    events = sim.events.drop_duplicates("uuid")
    starts = events[events.event == "session_started"][["distinct_id", "timestamp"]]
    users = sim.users[
        sim.users.exposed_at.notna() & ~sim.users.new_at_exposure & ~sim.users.is_demo
    ]
    users = users[users.exposed_at + pd.Timedelta(days=15) <= pd.Timestamp(sim.truth.data_end)]
    joined = starts.merge(users[["distinct_id", "exposed_at", "variant"]], on="distinct_id")
    day = (joined.timestamp.dt.normalize() - joined.exposed_at.dt.normalize()).dt.days
    per_user = joined[(day >= 1) & (day <= 14)].groupby("distinct_id").size()
    outcome = users.set_index("distinct_id").assign(sessions=per_user).fillna({"sessions": 0})
    arms = outcome.groupby("variant")["sessions"].agg(["mean", "var", "count"])
    t, c = arms.loc["test"], arms.loc["control"]
    ratio = t["mean"] / c["mean"]
    se = ratio * np.sqrt(
        t["var"] / (t["count"] * t["mean"] ** 2) + c["var"] / (c["count"] * c["mean"] ** 2)
    )
    assert abs(ratio - 1.2) < 4 * se


def test_pre_period_covariate_predicts_the_outcome(experiment):
    users = experiment.users
    returning = users[users.exposed_at.notna() & ~users.new_at_exposure]
    # people who opened the app once and came back later may have no sessions before
    assert (returning.pre_sessions > 0).mean() > 0.8
    assert (users.loc[users.new_at_exposure, "pre_sessions"] == 0).all()
    activity = experiment.events[experiment.events.event == "session_started"]
    total = activity.groupby("distinct_id").size()
    after = returning.set_index("distinct_id")
    corr = np.corrcoef(after.pre_sessions, total.reindex(after.index) - after.pre_sessions)[0, 1]
    assert corr > 0.3


def test_srm_loss_drops_test_exposures(experiment):
    users = experiment.users[experiment.users.exposed_at.notna()]
    logged = users[users.exposure_logged]
    test_share = (logged.variant == "test").mean()
    expected = 0.5 * 0.9 / (0.5 * 0.9 + 0.5)
    assert test_share == pytest.approx(expected, abs=0.015)
    assert (users.variant == "test").mean() == pytest.approx(0.5, abs=0.015)


def test_quick_start_only_on_a_new_test_users_first_sprint(experiment):
    events = experiment.events
    starts = events[events.event == "session_started"]
    props = starts.properties.map(json.loads)
    quick = starts[props.map(lambda p: p["start_method"] == "quick_start")]
    quick_props = quick.properties.map(json.loads)
    assert len(quick) > 0
    assert quick_props.map(lambda p: p["variant"] == "test" and p["session_number"] == 1).all()


def test_experiment_rejects_effects_the_model_cant_produce():
    with pytest.raises(ValueError, match="sessions_effect"):
        simulate(100, experiment=Experiment(sessions_effect=0.5))
    with pytest.raises(ValueError, match="activation_effect"):
        simulate(100, experiment=Experiment(activation_effect=0.9))
