"""The SQL models, run on 20,000 synthetic users, against the simulator's ground truth.

The truth is the population value the model implies, so a sample only lands near it. Where a
fixed tolerance is used it's at least 2.5 standard errors wide; elsewhere the tolerance is four
standard errors computed from the sample.
"""

import math
from datetime import date

import pandas as pd
import pytest

from liftlab.simulate import WINDOW_START


def _arrival_days(cohort_weeks: list[date]) -> list[int]:
    days = []
    for week in cohort_weeks:
        first = (week - WINDOW_START.date()).days
        days.extend(range(first, first + 7))
    return days


def test_all_six_models_build_and_are_labelled_synthetic(synthetic):
    _, con, _ = synthetic
    for table in (
        "stg_events",
        "fct_sessions",
        "dim_users",
        "funnel_activation",
        "retention_cohorts",
        "north_star_weekly",
    ):
        sources = con.execute(f"select distinct source from {table}").fetchall()
        assert sources == [("synthetic",)], table


def test_activation_rate_matches_truth(synthetic):
    sim, con, _ = synthetic
    sql_activation = con.execute(
        "select avg((activated_at is not null)::int) from dim_users where activation_window_closed"
    ).fetchone()[0]
    assert abs(sql_activation - sim.truth.activation_rate) < 0.01


def test_activation_agrees_user_by_user_with_the_simulator(synthetic):
    sim, con, _ = synthetic
    users = sim.users[~sim.users.is_demo]
    eligible = users[users.arrived_at + pd.Timedelta(hours=24) <= sim.truth.data_end]
    expected = set(eligible.loc[eligible.activated, "distinct_id"])
    activated = con.execute(
        "select user_id from dim_users where activation_window_closed and activated_at is not null"
    ).fetchall()
    actual = {row[0] for row in activated}
    assert actual == expected


def test_start_rate_matches_truth(synthetic):
    sim, con, _ = synthetic
    started = con.execute(
        "select overall_conversion from funnel_activation where step = 'session_started'"
    ).fetchone()[0]
    assert abs(started - sim.truth.start_rate) < 0.015


@pytest.mark.parametrize(("n", "tolerance"), [(1, None), (7, 0.01), (28, None)])
def test_retention_matches_truth(synthetic, n, tolerance):
    sim, con, _ = synthetic
    rows = con.execute(
        f"select cohort_week, cohort_users, d{n}_users from retention_cohorts "
        f"where d{n}_users is not null"
    ).fetchall()
    users = sum(r[1] for r in rows)
    sql_rate = sum(r[2] for r in rows) / users
    truth = sim.truth.retention(n, _arrival_days([r[0] for r in rows]))
    se = math.sqrt(truth * (1 - truth) / users)
    assert abs(sql_rate - truth) < (tolerance or 4 * se)
    assert 4 * se < 0.02  # the check is tight enough to catch a real error


def test_north_star_matches_truth_every_week(synthetic):
    sim, con, _ = synthetic
    expected = sim.truth.weekly_completed_sessions
    users = con.execute("select count(*) from dim_users").fetchone()[0]
    rows = con.execute(
        """
        select n.week_start, n.weekly_completed_sessions, coalesce(p.sum_sq, 0)
        from north_star_weekly n
        left join (
            select ended_week as week_start, sum(c * c) as sum_sq
            from (
                select ended_week, user_id, count(*) as c from fct_sessions
                where outcome = 'completed' group by all
            )
            group by ended_week
        ) p using (week_start)
        order by n.week_start
        """
    ).fetchall()
    assert [r[0] for r in rows] == list(expected)
    for week, wcs, sum_sq in rows:
        mean = wcs / users
        se = math.sqrt(users * (sum_sq / users - mean**2))  # SE of a sum of iid per-user counts
        assert abs(wcs - expected[week]) < 4 * se, week
        assert 4 * se < 0.2 * expected[week]

    totals = con.execute(
        "select sum(c), sum(c * c) from (select user_id, count(*) as c from fct_sessions "
        "where outcome = 'completed' group by user_id)"
    ).fetchone()
    se = math.sqrt(users * (totals[1] / users - (totals[0] / users) ** 2))
    assert abs(totals[0] - sum(expected.values())) < 4 * se
    assert 4 * se < 0.1 * sum(expected.values())


def test_north_star_identity_holds(synthetic):
    _, con, _ = synthetic
    for week, wcs, identity in con.execute(
        "select week_start, weekly_completed_sessions, wcs_from_identity from north_star_weekly"
    ).fetchall():
        assert identity == pytest.approx(wcs, rel=0.01), week


def test_funnel_steps_only_shrink(synthetic):
    _, con, _ = synthetic
    rows = con.execute(
        "select step, users, step_conversion, overall_conversion from funnel_activation "
        "order by step_number"
    ).fetchall()
    assert [r[0] for r in rows] == [
        "app_opened",
        "session_started",
        "session_completed",
        "second_session_7d",
    ]
    counts = [r[1] for r in rows]
    assert counts == sorted(counts, reverse=True)
    assert rows[0][2] == rows[0][3] == 1.0
    assert rows[2][3] == pytest.approx(rows[2][1] / rows[0][1])
