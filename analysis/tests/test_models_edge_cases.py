"""The SQL models on small hand-written event logs, one awkward case at a time."""

from datetime import date

from conftest import build_warehouse, event

SESSION = {"planned_minutes": 25, "goal_set": False}


def started(user, at, session_id, number=1, **extra):
    return event(
        user,
        "session_started",
        at,
        session_id=session_id,
        session_number=number,
        start_method="preset",
        **SESSION,
        **extra,
    )


def completed(user, at, session_id, uuid=None):
    return event(
        user,
        "session_completed",
        at,
        uuid=uuid,
        session_id=session_id,
        actual_minutes=25,
        pause_count=0,
        current_streak_days=1,
        is_first_completion=True,
        completed_while_away=False,
        **SESSION,
    )


def opened(user, at, uuid=None, **extra):
    return event(
        user,
        "app_opened",
        at,
        uuid=uuid,
        is_first_open=True,
        load_ms=400,
        referrer_type="direct",
        current_streak_days=0,
        **extra,
    )


def one(con, sql):
    return con.execute(sql).fetchone()


def test_user_with_no_sessions():
    con = build_warehouse([opened("u1", "2026-09-01 10:00")], data_end="2026-10-05")
    assert one(
        con, "select sessions_started, activated_at, activation_window_closed from dim_users"
    ) == (0, None, True)
    funnel = con.execute(
        "select step, users from funnel_activation order by step_number"
    ).fetchall()
    assert funnel == [
        ("app_opened", 1),
        ("session_started", 0),
        ("session_completed", 0),
        ("second_session_7d", 0),
    ]
    assert one(con, "select cohort_users, d1_users, d7_users from retention_cohorts") == (1, 0, 0)
    week = one(
        con,
        "select new_users, wau, weekly_completed_sessions, completion_rate "
        "from north_star_weekly where week_start = '2026-08-31'",
    )
    assert week == (1, 0, 0, None)


def test_duplicate_events_count_once():
    events = [
        opened("u1", "2026-09-01 10:00", uuid="e1"),
        opened("u1", "2026-09-01 10:00", uuid="e1"),
        started("u1", "2026-09-01 10:01", "s1") | {"uuid": "e2"},
        started("u1", "2026-09-01 10:01", "s1") | {"uuid": "e2"},
        completed("u1", "2026-09-01 10:26", "s1", uuid="e3"),
        completed("u1", "2026-09-01 10:26", "s1", uuid="e3"),
        completed("u1", "2026-09-01 10:27", "s1", uuid="e4"),  # a resend with a new uuid
    ]
    con = build_warehouse(events, data_end="2026-10-05")
    assert one(con, "select count(*) from stg_events") == (4,)
    assert one(con, "select count(*), max(ended_at)::varchar from fct_sessions") == (
        1,
        "2026-09-01 10:26:00",
    )
    assert one(
        con,
        "select weekly_completed_sessions from north_star_weekly where week_start = '2026-08-31'",
    ) == (1,)


def test_session_crossing_sunday_midnight():
    events = [
        opened("u1", "2026-09-05 12:00"),  # Saturday: day 0
        started("u1", "2026-09-06 23:50", "s1"),  # Sunday, day 1
        completed("u1", "2026-09-07 00:15", "s1"),  # Monday, the next ISO week
    ]
    con = build_warehouse(events, data_end="2026-10-05")
    row = one(con, "select started_date, started_week, ended_date, ended_week from fct_sessions")
    assert row == (date(2026, 9, 6), date(2026, 8, 31), date(2026, 9, 7), date(2026, 9, 7))
    weeks = dict(
        (r[0], r[1:])
        for r in con.execute(
            "select week_start, wau, weekly_completed_sessions, completion_rate, "
            "wcs_from_identity from north_star_weekly"
        ).fetchall()
    )
    # active (and the session counted for completion rate) in the week it started...
    assert weeks[date(2026, 8, 31)] == (1, 0, 1.0, 1.0)
    # ...but the North Star counts the completion in the week it happened
    assert weeks[date(2026, 9, 7)] == (0, 1, None, None)
    # retention goes by the day the session started: day 1, not day 2
    assert one(con, "select d1_users from retention_cohorts") == (1,)
    # completed 36 h after the first open, so not activated
    assert one(con, "select activated_at from dim_users") == (None,)


def test_activation_window_is_24_hours_from_the_first_open():
    events = [
        opened("in", "2026-09-01 10:00"),
        started("in", "2026-09-02 09:30", "s1"),
        completed("in", "2026-09-02 09:59:59", "s1"),
        opened("out", "2026-09-01 10:00"),
        started("out", "2026-09-02 09:40", "s2"),
        completed("out", "2026-09-02 10:00:01", "s2"),
    ]
    con = build_warehouse(events, data_end="2026-10-05")
    rows = con.execute(
        "select user_id, activated_at is not null from dim_users order by user_id"
    ).fetchall()
    assert rows == [("in", True), ("out", False)]


def test_sessions_without_an_end_event():
    events = [
        opened("u1", "2026-10-01 08:00"),
        started("u1", "2026-10-03 20:00", "stale"),  # 28 h before the cutoff
        started("u1", "2026-10-04 22:00", "open"),  # 2 h before the cutoff
    ]
    con = build_warehouse(events, data_end="2026-10-05")
    rows = con.execute(
        "select session_id, outcome, abandon_reason from fct_sessions order by session_id"
    ).fetchall()
    assert rows == [("open", "open", None), ("stale", "abandoned", "no_end_event")]
    week = one(
        con,
        "select sessions_started, completion_rate, abandon_rate "
        "from north_star_weekly where week_start = '2026-09-28'",
    )
    assert week == (2, 0.0, 1.0)  # the open session is left out of both rates


def test_demo_and_unplanned_events_are_dropped():
    events = [
        opened("u1", "2026-09-01 10:00"),
        event("u1", "$pageview", "2026-09-01 10:00"),
        event("u1", "$autocapture", "2026-09-01 10:01"),
        opened("demo", "2026-09-01 11:00") | {"properties": '{"is_demo": true}'},
    ]
    con = build_warehouse(events, data_end="2026-10-05")
    assert con.execute("select user_id, event from stg_events").fetchall() == [("u1", "app_opened")]


def test_only_complete_weeks_and_periods_are_reported():
    events = [opened("u1", "2026-09-01 10:00"), opened("u2", "2026-09-30 10:00")]
    con = build_warehouse(events, data_end="2026-10-01 12:00")
    weeks = [r[0] for r in con.execute("select week_start from north_star_weekly").fetchall()]
    assert weeks[-1] == date(2026, 9, 21)  # the week of Sep 28 hasn't ended
    last = one(
        con, "select d1_users, d7_users from retention_cohorts where cohort_week = '2026-09-28'"
    )
    assert last == (None, None)
