"""Simulated StudySprint users with known ground truth.

Every user gets a latent motivation m ~ N(0, 1). It drives everything the metrics measure:
whether they start and finish a first sprint, how often they come back, how often they finish,
and how quickly they drift away for good. Events follow docs/TRACKING_PLAN.md and are shaped
like a PostHog export (uuid, event, distinct_id, timestamp, properties as JSON), so the
warehouse treats them exactly like real data.

Because the model is known, so are the true values of the metrics. `GroundTruth` computes them
from the model itself (Gauss-Hermite quadrature over motivation, closed-form integrals over
first-day timing), not from the sample, so the SQL can be checked against them within sampling
error. This data is synthetic and is always labelled that way: `source = 'synthetic'`.
"""

import bisect
import json
import math
import random
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

DAY = 86_400
DAY_MINUTES = 1_440
LENGTHS = (15, 25, 50)
WINDOW_START = datetime(2026, 8, 31)  # a Monday, the first week of the fall semester
APP_URL = "https://singha105.github.io/liftlab/"
QUADRATURE_NODES = 80

# (UTC offset in hours, share of users): mostly North American students, during the
# semester's daylight-saving months.
TIMEZONES = ((-4, 0.32), (-5, 0.16), (-6, 0.05), (-7, 0.15), (1, 0.07), (2, 0.10), (5.5, 0.15))
# When students open the app and study, by local hour (relative weights).
LOCAL_HOURS = (
    0.6, 0.3, 0.15, 0.1, 0.1, 0.15, 0.3, 0.6, 1.0, 1.4, 1.6, 1.6,
    1.4, 1.5, 1.7, 1.7, 1.6, 1.5, 1.6, 1.9, 2.1, 2.0, 1.6, 1.1,
)  # fmt: skip
ARRIVAL_WEEKDAY = (1.15, 1.10, 1.05, 0.95, 0.75, 0.70, 1.30)  # Mon..Sun; Sunday-night planners
ARRIVAL_GROWTH = 0.6  # the last day gets 60% more new users than the first

# The first 24 hours. A first sprint starts within minutes of arriving or hours later, and a
# retry after giving up starts 90 minutes to 5 hours after the first one began. The latest a
# first-day sprint can end is 16 h + 5 h + 80 min after arrival, so every first-day completion
# lands inside the 24-hour activation window and activation never depends on timing.
START_NOW = (0.6, 1 / 3, 4.0)  # share, then bounds of the delay in minutes
START_LATER = (0.4, 60.0, 960.0)
RETRY_AFTER = (90.0, 300.0)

# Later days. A visit's sprints start at most VISIT_SLOT minutes apart (a 50-minute sprint,
# up to 30 minutes of pauses, up to 20 minutes between sprints), and a visit is placed so all
# of them start on the same UTC day; the last one may still run past midnight. On the day after
# arrival, a visit starts at least 24 hours after the first open, so it can't count toward
# activation.
VISIT_SLOT = 100
PREFERRED_LENGTH_SHARE = 0.8
MAX_EXTRA_SPRINTS = 2
MAX_PAUSES = 3
PAUSE_RATE = 0.25  # expected pauses in a 25-minute sprint
AWAY_SHARE = 0.07  # finished with the page closed, confirmed on return
ABANDON_REASONS = (("user_ended", 0.80), ("page_closed", 0.08), ("stale", 0.04), (None, 0.08))
HOME_STREAK_VIEW = 0.12
USER_SUMMARY_VIEW = 0.05
DEMO_SHARE = 0.004  # people trying ?demo=1; the warehouse drops them
DUPLICATE_SHARE = 0.003  # events delivered twice with the same uuid

DEVICES = (
    # device type, share, (browser, os) choices, median load_ms
    ("Desktop", 0.68, (("Chrome", "Windows"), ("Chrome", "Mac OS X"), ("Safari", "Mac OS X"),
                       ("Firefox", "Windows"), ("Edge", "Windows"), ("Chrome", "Chrome OS")), 380),
    ("Mobile", 0.29, (("Mobile Safari", "iOS"), ("Chrome", "Android")), 700),
    ("Tablet", 0.03, (("Mobile Safari", "iOS"),), 600),
)  # fmt: skip
FIRST_REFERRER = (("direct", 0.40), ("search", 0.30), ("social", 0.20), ("other", 0.10))
RETURN_REFERRER = (("direct", 0.90), ("search", 0.05), ("social", 0.03), ("other", 0.02))
DEPLOY_DAYS = (0, 9, 20, 33, 47)


def _logistic(coef: tuple[float, float], m, shift: float = 0.0):
    return 1 / (1 + np.exp(-(coef[0] + coef[1] * m + shift)))


@dataclass(frozen=True)
class Behavior:
    """The user model. Each (a, b) pair is a logit a + b * m in motivation m.

    The defaults are tuned to the baselines assumed in docs/EXPERIMENT_BACKLOG.md: about half
    of new users start a sprint within 24 hours, about 30% finish one (activation), D7
    retention near 15%, and about three in four sessions completed.
    """

    # The first 24 hours
    start: tuple[float, float] = (0.0, 1.0)
    finish: tuple[float, float] = (0.45, 0.8)  # a 25-minute sprint without a goal
    first_sprint_penalty: float = 0.75
    goal_bonus: float = 0.35
    length_penalty: tuple[float, float, float] = (-0.4, 0.0, 0.7)  # 15, 25, 50 minutes
    retry: tuple[float, float] = (-1.3, 0.6)  # try again the same day after giving up
    goal: tuple[float, float] = (-0.3, 0.4)
    first_length: tuple[float, float, float] = (0.15, 0.75, 0.10)  # 25 is preselected
    preferred_length: tuple[tuple[float, float], ...] = ((-0.5, -0.3), (0.6, 0.0), (-0.7, 0.5))
    # After the first day: a visit on any day the user is still around, with a weekday factor
    active_cap: float = 0.65
    active_activated: tuple[float, float] = (1.0, 0.9)
    active_not_activated: tuple[float, float] = (-2.4, 1.0)
    churn_activated: tuple[float, float] = (-3.3, -0.6)  # daily chance of leaving for good
    churn_not_activated: tuple[float, float] = (-1.5, -0.5)
    extra_sprints: tuple[float, float] = (-1.3, 0.4)  # log of a Poisson mean, capped at 2
    weekday_activity: tuple[float, ...] = (1.08, 1.10, 1.08, 1.02, 0.82, 0.74, 1.16)

    def p_start(self, m, shift: float = 0.0):
        return _logistic(self.start, m, shift)

    def p_goal(self, m):
        return _logistic(self.goal, m)

    def p_retry(self, m):
        return _logistic(self.retry, m)

    def p_finish(self, m, length: int, goal_set, first):
        logit = (
            self.finish[0]
            + self.finish[1] * m
            - self.length_penalty[length]
            + self.goal_bonus * goal_set
            - self.first_sprint_penalty * first
        )
        return 1 / (1 + np.exp(-logit))

    def preferred_length_mix(self, m):
        logits = np.stack(
            [a + b * np.asarray(m, dtype=float) for a, b in self.preferred_length], -1
        )
        weights = np.exp(logits - logits.max(-1, keepdims=True))
        return weights / weights.sum(-1, keepdims=True)

    def length_mix(self, m):
        """Chance of each length for any sprint but the first."""
        share = PREFERRED_LENGTH_SHARE
        return share * self.preferred_length_mix(m) + (1 - share) / len(LENGTHS)

    def p_finish_first(self, m):
        return self._p_finish_mix(m, np.asarray(self.first_length), first=True)

    def p_finish_later(self, m):
        return self._p_finish_mix(m, self.length_mix(m), first=False)

    def _p_finish_mix(self, m, mix, first: bool):
        goal = self.p_goal(m)
        return sum(
            mix[..., i]
            * (goal * self.p_finish(m, i, 1, first) + (1 - goal) * self.p_finish(m, i, 0, first))
            for i in range(len(LENGTHS))
        )

    def p_active(self, m, activated: bool):
        coef = self.active_activated if activated else self.active_not_activated
        return self.active_cap * _logistic(coef, m)

    def p_churn(self, m, activated: bool):
        return _logistic(self.churn_activated if activated else self.churn_not_activated, m)

    def extra_sprint_mean(self, m):
        return np.exp(self.extra_sprints[0] + self.extra_sprints[1] * m)

    def sprints_per_visit(self, m, room2: float = 1.0, room3: float = 1.0):
        """Expected sprints in a visit; room2/room3 are the chances there's time for a 2nd/3rd."""
        mu = self.extra_sprint_mean(m)
        at_least_one = 1 - np.exp(-mu)
        at_least_two = 1 - np.exp(-mu) * (1 + mu)
        return 1 + at_least_one * room2 + at_least_two * room3


# The pre-registered Quick Start test (docs/experiments/EXP-001.md) and its feature flag key.
QUICK_START_KEY = "exp-001"


@dataclass(frozen=True)
class Experiment:
    """A test that starts `start_day` days into the window and runs to the end.

    Users are exposed at their first visit on or after the start: new users when they first
    open the app, and (with `audience="all"`) returning users at their first visit after the
    start. The test arm gets two effects:

    - `activation_effect`: the absolute change in new users' activation rate. The simulator
      shifts their chance of starting a first sprint until the true effect is exactly this.
    - `sessions_effect`: the relative change in how often exposed users visit after their
      exposure day. For returning users, expected sessions on every later day scale by exactly
      1 + sessions_effect, so any per-user window after exposure does too.

    `srm_loss` is the share of test users whose exposure event never arrives, the classic cause
    of a sample-ratio mismatch. They still get the test experience.
    """

    key: str = QUICK_START_KEY
    start_day: int = 28
    audience: str = "all"
    activation_effect: float = 0.0
    sessions_effect: float = 0.0
    test_share: float = 0.5
    srm_loss: float = 0.0


@dataclass(frozen=True)
class ExperimentTruth:
    key: str
    start_day: int
    audience: str
    test_share: float
    srm_loss: float
    start_shift: float  # log-odds added to a new test user's chance of starting a sprint
    activation_control: float
    activation_test: float
    activation_effect: float
    sessions_lift: float


@dataclass(frozen=True)
class _FirstDayTiming:
    first: float  # chance the first sprint starts on the next UTC day
    retry: float  # chance a retry starts on the next UTC day
    room2: float  # chance a visit the day after arrival has time for a 2nd sprint
    room3: float


def arrival_weights(days: int) -> np.ndarray:
    """Chance a new user arrives on each day of the window."""
    day = np.arange(days)
    weights = (1 + ARRIVAL_GROWTH * day / max(days - 1, 1)) * np.asarray(ARRIVAL_WEEKDAY)[day % 7]
    return weights / weights.sum()


def minute_profiles() -> np.ndarray:
    """Chance of each UTC minute of the day, one row per timezone."""
    utc = np.arange(DAY_MINUTES)
    rows = []
    for offset, _ in TIMEZONES:
        local = (utc + round(offset * 60)) % DAY_MINUTES
        weights = np.asarray(LOCAL_HOURS)[local // 60]
        rows.append(weights / weights.sum())
    return np.array(rows)


def _timezone_shares() -> np.ndarray:
    shares = np.array([share for _, share in TIMEZONES])
    return shares / shares.sum()


def _sf_uniform(t, lo: float, hi: float):
    """P(U >= t) for U ~ Uniform(lo, hi)."""
    return np.clip((hi - t) / (hi - lo), 0, 1)


def _ramp_area(u):
    """Integral of clip(s, 0, 1) from -inf to u."""
    return np.where(u <= 0, 0.0, np.where(u < 1, u * u / 2, u - 0.5))


def _sf_uniform_sum(t, a: float, b: float, c: float, d: float):
    """P(X + R >= t) for X ~ Uniform(a, b) and R ~ Uniform(c, d), independent."""
    width = d - c
    return width * (_ramp_area((b - t + d) / width) - _ramp_area((a - t + d) / width)) / (b - a)


def _first_day_timing() -> _FirstDayTiming:
    arrival = _timezone_shares() @ minute_profiles()
    steps = 16  # arrival is uniform within its minute; integrate with the midpoint rule
    tau = (np.arange(DAY_MINUTES)[:, None] + (np.arange(steps) + 0.5) / steps).ravel()
    weight = np.repeat(arrival / steps, steps)
    to_midnight = DAY_MINUTES - tau
    delays = (START_NOW, START_LATER)
    first = sum(share * _sf_uniform(to_midnight, lo, hi) for share, lo, hi in delays)
    retry = sum(
        share * _sf_uniform_sum(to_midnight, lo, hi, *RETRY_AFTER) for share, lo, hi in delays
    )
    room = (DAY_MINUTES - 1 - np.arange(DAY_MINUTES)) // VISIT_SLOT
    return _FirstDayTiming(
        first=float(weight @ first),
        retry=float(weight @ retry),
        room2=float(arrival[room >= 1].sum()),
        room3=float(arrival[room >= 2].sum()),
    )


_ACTIVATED_BRANCHES = ("finished_first", "finished_retry")


class GroundTruth:
    """The metric values the behaviour model implies for the whole population.

    These are expectations, not sample statistics: a simulated sample lands near them, within
    sampling error. Demo users are left out, as the warehouse leaves them out.
    """

    def __init__(
        self,
        behavior: Behavior,
        *,
        n_users: int,
        weeks: int,
        start: datetime,
        experiment: Experiment | None,
    ):
        self.behavior = behavior
        self.n_users = n_users
        self.weeks = weeks
        self.start = start
        self.data_end = start + timedelta(weeks=weeks)
        self._arrivals = arrival_weights(weeks * 7)
        nodes, weights = np.polynomial.hermite_e.hermegauss(QUADRATURE_NODES)
        self._m = nodes
        self._w = weights / weights.sum()
        self._timing = _first_day_timing()

        self.start_rate = self._mean(behavior.p_start(nodes))
        self.activation_rate = self._activation(0.0)
        self.retention_curve = {n: self.retention(n) for n in range(1, 29)}
        self.experiment = None if experiment is None else self._experiment(experiment)
        self.weekly_completed_sessions = (
            self._weekly_completed_sessions() if experiment is None else None
        )

    def retention(self, n: int, arrival_days=None) -> float:
        """Share of new users with a session started on day n (UTC) after their first open.

        `arrival_days` (day indexes into the window) restricts the population to users who
        arrived on those days, to match cohorts the SQL can report.
        """
        weights = self._arrivals.copy()
        if arrival_days is not None:
            keep = np.zeros_like(weights, dtype=bool)
            keep[list(arrival_days)] = True
            weights = np.where(keep, weights, 0.0)
        weights /= weights.sum()
        weekday = np.asarray(self.behavior.weekday_activity)[(np.arange(len(weights)) + n) % 7]
        branches = self._branches()
        if n == 1:
            day1 = self._day1_start_chance()
            per_day = np.zeros(len(weights))
            for name, share in branches.items():
                visit = self._visit_chance(name in _ACTIVATED_BRANCHES, 1)
                missed = (1 - day1[name]) * (1 - np.outer(weekday, visit))
                per_day += (1 - missed) @ (share * self._w)
            return float(weights @ per_day)
        activated = branches["finished_first"] + branches["finished_retry"]
        visits = activated * self._visit_chance(True, n)
        visits += (1 - activated) * self._visit_chance(False, n)
        return float(weights @ weekday) * self._mean(visits)

    def as_rows(self) -> list[tuple[str, float]]:
        """(metric, value) pairs for the warehouse's sim_truth table."""
        rows = [("start_rate", self.start_rate), ("activation_rate", self.activation_rate)]
        rows += [(f"retention_d{n}", value) for n, value in self.retention_curve.items()]
        for week, value in (self.weekly_completed_sessions or {}).items():
            rows.append((f"weekly_completed_sessions_{week.isoformat()}", value))
        if self.experiment is not None:
            for name in (
                "start_shift",
                "activation_control",
                "activation_test",
                "activation_effect",
                "sessions_lift",
            ):
                rows.append((f"experiment_{name}", getattr(self.experiment, name)))
        return rows

    def _mean(self, values) -> float:
        return float(self._w @ values)

    def _branches(self, shift: float = 0.0) -> dict[str, np.ndarray]:
        """How the first 24 hours go, as shares of new users at each motivation node."""
        b, m = self.behavior, self._m
        started = b.p_start(m, shift)
        first = b.p_finish_first(m)
        later = b.p_finish_later(m)
        retry = b.p_retry(m)
        gave_up = started * (1 - first)
        return {
            "finished_first": started * first,
            "finished_retry": gave_up * retry * later,
            "failed_retry": gave_up * retry * (1 - later),
            "no_retry": gave_up * (1 - retry),
            "never_started": 1 - started,
        }

    def _activation(self, shift: float) -> float:
        branches = self._branches(shift)
        return self._mean(branches["finished_first"] + branches["finished_retry"])

    def _day1_start_chance(self) -> dict[str, float]:
        """Chance a first-day sprint starts on the next UTC day, by branch."""
        first, retry = self._timing.first, self._timing.retry
        return {
            "finished_first": first,
            "no_retry": first,
            "finished_retry": retry,
            "failed_retry": retry,
            "never_started": 0.0,
        }

    def _visit_chance(self, activated: bool, age: int) -> np.ndarray:
        """Chance of a visit `age` days after arrival, before the weekday factor."""
        b, m = self.behavior, self._m
        return (1 - b.p_churn(m, activated)) ** age * b.p_active(m, activated)

    def _weekly_completed_sessions(self) -> dict[date, float]:
        """Expected completed sessions per ISO week, by the day each session started."""
        b, m = self.behavior, self._m
        days = self.weeks * 7
        branches = self._branches()
        activated = branches["finished_first"] + branches["finished_retry"]
        finish = b.p_finish_later(m)
        timing = self._timing
        first_day = (
            self._mean(
                branches["finished_first"] * (1 - timing.first)
                + branches["finished_retry"] * (1 - timing.retry)
            ),
            self._mean(
                branches["finished_first"] * timing.first
                + branches["finished_retry"] * timing.retry
            ),
        )
        per_visit = b.sprints_per_visit(m)
        per_visit_day1 = b.sprints_per_visit(m, timing.room2, timing.room3)
        later = np.zeros(days)  # expected completions `age` days after arrival, no weekday factor
        for age in range(1, days):
            visits = activated * self._visit_chance(True, age)
            visits += (1 - activated) * self._visit_chance(False, age)
            later[age] = self._mean(visits * (per_visit_day1 if age == 1 else per_visit) * finish)
        weekday = np.asarray(b.weekday_activity)
        per_day = np.zeros(days)
        for day in range(days):
            arrivals = self._arrivals[: day + 1][::-1]  # arrivals[age] arrived `age` days ago
            per_day[day] = arrivals[0] * first_day[0]
            if day >= 1:
                per_day[day] += arrivals[1] * first_day[1]
                per_day[day] += weekday[day % 7] * (arrivals[1:] @ later[1 : day + 1])
        per_day *= self.n_users * (1 - DEMO_SHARE)
        return {
            (self.start + timedelta(weeks=w)).date(): float(per_day[7 * w : 7 * w + 7].sum())
            for w in range(self.weeks)
        }

    def _experiment(self, experiment: Experiment) -> ExperimentTruth:
        b = self.behavior
        ceiling = 1 / (b.active_cap * max(b.weekday_activity)) - 1
        if not -1 < experiment.sessions_effect <= ceiling:
            raise ValueError(f"sessions_effect must be in (-1, {ceiling:.3f}]")
        if experiment.audience not in ("all", "new"):
            raise ValueError("audience must be 'all' or 'new'")
        target = self.activation_rate + experiment.activation_effect
        lo, hi = -20.0, 20.0
        if not self._activation(lo) < target < self._activation(hi):
            raise ValueError("activation_effect is outside what the model can produce")
        shift = 0.0
        if experiment.activation_effect:
            for _ in range(200):
                shift = (lo + hi) / 2
                if self._activation(shift) < target:
                    lo = shift
                else:
                    hi = shift
        test = self._activation(shift)
        return ExperimentTruth(
            key=experiment.key,
            start_day=experiment.start_day,
            audience=experiment.audience,
            test_share=experiment.test_share,
            srm_loss=experiment.srm_loss,
            start_shift=shift,
            activation_control=self.activation_rate,
            activation_test=test,
            activation_effect=test - self.activation_rate,
            sessions_lift=experiment.sessions_effect,
        )


@dataclass(frozen=True)
class Simulation:
    events: pd.DataFrame  # one row per event, PostHog export shape
    users: pd.DataFrame  # one row per user: latent traits and simulator-side facts
    truth: GroundTruth


def simulate(
    n_users: int = 20_000,
    *,
    seed: int = 7,
    weeks: int = 8,
    start: datetime = WINDOW_START,
    experiment: Experiment | None = None,
    behavior: Behavior | None = None,
) -> Simulation:
    """Simulate `n_users` new users arriving over `weeks` weeks. Same seed, same output."""
    if start.weekday() != 0 or start != datetime(start.year, start.month, start.day):
        raise ValueError("start must be a Monday at 00:00 UTC, so weeks line up with ISO weeks")
    behavior = behavior or Behavior()
    truth = GroundTruth(behavior, n_users=n_users, weeks=weeks, start=start, experiment=experiment)
    run = _Run(n_users, seed, weeks * 7, behavior, experiment, truth)
    events, users = run.simulate()
    return Simulation(events=events, users=users, truth=truth)


def _pick(r: random.Random, options) -> object:
    u = r.random()
    for value, share in options:
        u -= share
        if u < 0:
            return value
    return options[-1][0]


def _poisson(r: random.Random, mean: float, cap: int) -> int:
    limit, k, p = math.exp(-mean), 0, r.random()
    while p > limit and k < cap:
        k += 1
        p *= r.random()
    return k


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


class _Run:
    """One simulation: per-user draws are vectorised, timelines are built user by user."""

    def __init__(self, n_users, seed, days, behavior, experiment, truth):
        rng = np.random.default_rng(seed)
        self.rng = rng
        self.n = n_users
        self.days = days
        self.cutoff = days * DAY
        self.behavior = b = behavior
        self.experiment = experiment
        self.start_shift = truth.experiment.start_shift if truth.experiment else 0.0

        self.arrival_day = rng.choice(days, size=n_users, p=arrival_weights(days)).tolist()
        tz = rng.choice(len(TIMEZONES), size=n_users, p=_timezone_shares())
        self.tz = tz.tolist()
        profiles = minute_profiles()
        self.minute_cdf = [np.concatenate(([0.0], np.cumsum(p))).tolist() for p in profiles]
        u = rng.random(n_users)
        minute = np.zeros(n_users, dtype=int)
        for g, cdf in enumerate(self.minute_cdf):
            rows = tz == g
            minute[rows] = np.searchsorted(cdf, u[rows], side="right") - 1
        minute = np.clip(minute, 0, DAY_MINUTES - 1)
        self.arrival_minute = minute.tolist()
        self.arrival_offset = ((minute + rng.random(n_users)) * 60).tolist()

        m = rng.standard_normal(n_users)
        self.m = m.tolist()
        self.demo = (rng.random(n_users) < DEMO_SHARE).tolist()
        self.test = (rng.random(n_users) < (experiment.test_share if experiment else 0.5)).tolist()
        self.srm_lost = (rng.random(n_users) < (experiment.srm_loss if experiment else 0)).tolist()
        pref_cdf = np.cumsum(b.preferred_length_mix(m), axis=1)
        self.preferred = (rng.random(n_users)[:, None] > pref_cdf).sum(axis=1).clip(0, 2).tolist()
        shares = np.array([d[1] for d in DEVICES])
        self.device = rng.choice(len(DEVICES), size=n_users, p=shares / shares.sum()).tolist()
        self.user_ids = [str(uuid.UUID(bytes=rng.bytes(16), version=4)) for _ in range(n_users)]
        self.versions = [rng.bytes(4).hex()[:7] for _ in DEPLOY_DAYS]

        self.p_start = b.p_start(m).tolist()
        self.p_start_test = b.p_start(m, self.start_shift).tolist()
        self.p_goal = b.p_goal(m).tolist()
        self.p_retry = b.p_retry(m).tolist()
        self.finish_base = (b.finish[0] + b.finish[1] * m).tolist()
        self.active = (b.p_active(m, True).tolist(), b.p_active(m, False).tolist())
        self.churn = (b.p_churn(m, True).tolist(), b.p_churn(m, False).tolist())
        self.extra_mean = b.extra_sprint_mean(m).tolist()
        self.first_length = tuple(enumerate(b.first_length))
        self.py = random.Random(int(rng.integers(2**63)))

    def simulate(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        rows: list[tuple] = []
        users: list[dict] = []
        for i in range(self.n):
            timeline, facts, exposed_at = self._timeline(i)
            rows.extend(self._properties(i, timeline, exposed_at))
            users.append(facts)

        duplicates = self.rng.choice(
            len(rows), size=int(len(rows) * DUPLICATE_SHARE), replace=False
        )
        rows.extend(rows[j] for j in sorted(duplicates.tolist()))
        rows.sort(key=lambda row: row[3])
        seconds = np.array([row[3] for row in rows])
        events = pd.DataFrame(
            {
                "uuid": [row[0] for row in rows],
                "event": [row[1] for row in rows],
                "distinct_id": [row[2] for row in rows],
                "timestamp": np.datetime64(WINDOW_START, "ms")
                + (seconds * 1000).astype("timedelta64[ms]"),
                "properties": [row[4] for row in rows],
            }
        )
        return events, pd.DataFrame(users)

    # Pass 1: what the user does, and when.

    def _timeline(self, i: int) -> tuple[list, dict, float | None]:
        r = self.py.random
        exp = self.experiment
        arrival = self.arrival_day[i]
        t0 = arrival * DAY + self.arrival_offset[i]
        events: list = []
        self._open(events, t0, first=True)

        exposed_at = exposure_day = None
        is_new_in_test = False
        if exp and arrival >= exp.start_day:
            exposed_at, exposure_day = t0 + 0.05, arrival
            self._expose(events, i, exposed_at)
            is_new_in_test = self.test[i]
        pending_exposure = bool(exp and exp.audience == "all" and arrival < exp.start_day)

        activated = False
        if r() < (self.p_start_test[i] if is_new_in_test else self.p_start[i]):
            _, lo, hi = START_NOW if r() < START_NOW[0] else START_LATER
            delay = r() * (hi - lo) + lo
            t1 = t0 + delay * 60
            if delay >= 60:
                self._open(events, t1 - (r() * 115 + 5))
            length = _pick(self.py, self.first_length)
            goal = r() < self.p_goal[i]
            finished = r() < self._p_finish(i, length, goal, first=True)
            quick = is_new_in_test and exp.key == QUICK_START_KEY
            self._sprint(events, t1, length, goal, finished, "quick_start" if quick else "preset")
            if finished:
                activated = True
            elif r() < self.p_retry[i]:
                t2 = t1 + (r() * (RETRY_AFTER[1] - RETRY_AFTER[0]) + RETRY_AFTER[0]) * 60
                self._open(events, t2 - (r() * 115 + 5))
                length, goal = self._choose(i)
                activated = r() < self._p_finish(i, length, goal, first=False)
                self._sprint(events, t2, length, goal, activated, "preset")

        status = 0 if activated else 1
        churn, active = self.churn[status][i], self.active[status][i]
        leaves = 1 + int(math.log(1 - r()) / math.log(1 - churn))  # first day not around
        lift = exp.sessions_effect if exp and self.test[i] else 0.0
        weekday = self.behavior.weekday_activity
        for age in range(1, min(leaves, self.days - arrival)):
            day = arrival + age
            chance = active * weekday[day % 7]
            if lift and exposure_day is not None and day > exposure_day:
                chance *= 1 + lift
            if r() >= chance:
                continue
            sprints = 1 + _poisson(self.py, self.extra_mean[i], MAX_EXTRA_SPRINTS)
            earliest = self.arrival_minute[i] if age == 1 else 0
            sprints = min(sprints, 1 + (DAY_MINUTES - earliest - 1) // VISIT_SLOT)
            latest = DAY_MINUTES - (sprints - 1) * VISIT_SLOT
            t = day * DAY + self._minute(self.tz[i], earliest, latest) * 60
            if age == 1:  # strictly after the 24-hour activation window
                t = max(t, t0 + DAY + 1)
            opened = t - (r() * 115 + 5)
            self._open(events, opened)
            if pending_exposure and day >= exp.start_day:
                pending_exposure = False
                exposed_at, exposure_day = opened + 0.05, day
                self._expose(events, i, exposed_at)
            if r() < HOME_STREAK_VIEW:
                events.append((opened + 2, len(events), "streak_viewed", {"surface": "home"}))
            if r() < USER_SUMMARY_VIEW:
                events.append(
                    (opened + 3, len(events), "weekly_summary_viewed", {"opened_by": "user"})
                )
            for _ in range(sprints):
                length, goal = self._choose(i)
                finished = r() < self._p_finish(i, length, goal, first=False)
                t = self._sprint(events, t, length, goal, finished, "preset") + r() * 1140 + 60

        pre_sessions = None
        if exposed_at is not None:
            pre_sessions = sum(
                1
                for t, _, name, _ in events
                if name == "session_started" and exposed_at - 28 * DAY <= t < exposed_at
            )
        facts = {
            "distinct_id": self.user_ids[i],
            "arrival_day": arrival,
            "arrived_at": WINDOW_START + timedelta(seconds=t0),
            "tz_offset_hours": TIMEZONES[self.tz[i]][0],
            "motivation": self.m[i],
            "is_demo": self.demo[i],
            "activated": activated,
            "variant": ("test" if self.test[i] else "control") if exposed_at is not None else None,
            "exposed_at": None
            if exposed_at is None
            else WINDOW_START + timedelta(seconds=exposed_at),
            "exposure_logged": exposed_at is not None and not (self.test[i] and self.srm_lost[i]),
            "new_at_exposure": exposed_at is not None and exposure_day == arrival,
            "pre_sessions": pre_sessions,
        }
        return events, facts, exposed_at

    def _choose(self, i: int) -> tuple[int, bool]:
        r = self.py.random
        length = self.preferred[i] if r() < PREFERRED_LENGTH_SHARE else int(r() * 3)
        return length, r() < self.p_goal[i]

    def _p_finish(self, i: int, length: int, goal: bool, first: bool) -> float:
        b = self.behavior
        return _sigmoid(
            self.finish_base[i]
            - b.length_penalty[length]
            + b.goal_bonus * goal
            - b.first_sprint_penalty * first
        )

    def _minute(self, tz: int, earliest: int, latest: int) -> float:
        """A minute of the UTC day in [earliest, latest), following the timezone's profile."""
        cdf = self.minute_cdf[tz]
        u = cdf[earliest] + self.py.random() * (cdf[latest] - cdf[earliest])
        minute = min(max(bisect.bisect_right(cdf, u) - 1, earliest), latest - 1)
        return minute + self.py.random()

    def _open(self, events: list, t: float, first: bool = False) -> None:
        events.append((t, len(events), "app_opened", {"first": first}))

    def _expose(self, events: list, i: int, t: float) -> None:
        if not (self.test[i] and self.srm_lost[i]):
            events.append((t, len(events), "experiment_exposed", {}))

    def _sprint(self, events, t, length, goal, finished, method) -> float:
        """Add one sprint starting at t; return when it stopped occupying the user."""
        r = self.py.random
        planned = LENGTHS[length]
        session_id = str(uuid.UUID(int=self.py.getrandbits(128), version=4))
        base = {"session_id": session_id, "planned_minutes": planned, "goal_set": goal}
        events.append((t, len(events), "session_started", {**base, "start_method": method}))
        if finished:
            pauses = _poisson(self.py, PAUSE_RATE * planned / 25, MAX_PAUSES)
            paused = sum(r() * 540 + 60 for _ in range(pauses))
            end = t + planned * 60 + paused
            done = {
                **base,
                "actual_minutes": round((planned * 60 + paused) / 60),
                "pause_count": pauses,
                "completed_while_away": False,
            }
            seen = end
            if r() < AWAY_SHARE:
                seen = end + r() * 10_500 + 300
                if seen >= self.cutoff:  # the answer never made it into the export
                    return end
                done["completed_while_away"] = True
                self._open(events, seen)
            events.append((end, len(events), "session_completed", done))
            events.append(
                (seen + 1, len(events), "streak_viewed", {"surface": "completion_screen"})
            )
            return end

        progress = self.py.betavariate(0.9, 1.6)
        focused = max(5, int(planned * 60 * progress))
        pauses = _poisson(self.py, PAUSE_RATE * planned / 25 * progress, MAX_PAUSES)
        paused = sum(r() * 540 + 60 for _ in range(pauses))
        reason = _pick(self.py, ABANDON_REASONS)
        gave_up = {**base, "elapsed_seconds": focused, "pause_count": pauses, "reason": reason}
        end = t + focused + paused
        if reason == "user_ended":
            events.append((end, len(events), "session_abandoned", gave_up))
        elif reason == "page_closed":  # the timer ran out with the page closed; they said no
            end = t + planned * 60 + paused
            back = end + r() * 10_500 + 300
            self._open(events, back)
            gave_up["elapsed_seconds"] = planned * 60
            events.append((back + 1, len(events), "session_abandoned", gave_up))
        elif reason == "stale":  # paused and left for over a day
            back = t + (r() * 35 + 25) * 3600
            self._open(events, back)
            events.append((back + 1, len(events), "session_abandoned", gave_up))
        return end  # reason None: the tab closed for good, so no end event at all

    # Pass 2: the properties that depend on history (streaks, counts, the weekly summary).

    def _properties(self, i: int, timeline: list, exposed_at: float | None) -> list[tuple]:
        r = self.py.random
        exp = self.experiment
        offset = round(TIMEZONES[self.tz[i]][0] * 3600)
        device, _, browsers, median_load = DEVICES[self.device[i]]
        browser, os_name = browsers[int(r() * len(browsers))]
        posthog = {
            "$browser": browser,
            "$os": os_name,
            "$device_type": device,
            "$current_url": APP_URL,
            "$lib": "web",
            "$lib_version": "1.442.1",
        }
        user_id = self.user_ids[i]
        demo = self.demo[i]

        opens = starts = 0
        days: set[int] = set()  # local days with a completed sprint
        weeks: dict[int, list[int]] = {}  # local week -> [sprints, minutes]
        longest = 0
        summary_week = None
        rows = []

        def streak(day: int) -> int:
            if day not in days:
                day -= 1
            run = 0
            while day in days:
                run += 1
                day -= 1
            return run

        def emit(t: float, name: str, props: dict) -> None:
            if t >= self.cutoff:
                return
            arm = exposed_at is not None and t >= exposed_at
            day = int(t // DAY)
            props = {
                **props,
                "app_version": self.versions[bisect.bisect_right(DEPLOY_DAYS, day) - 1],
                "experiment_key": exp.key if arm else "none",
                "variant": ("test" if self.test[i] else "control") if arm else "none",
                "is_demo": demo,
                **posthog,
            }
            event_id = str(uuid.UUID(int=self.py.getrandbits(128), version=4))
            rows.append((event_id, name, user_id, t, json.dumps(props, separators=(",", ":"))))

        for t, _, name, props in sorted(timeline, key=lambda e: (e[0], e[1])):
            local_day = int((t + offset) // DAY)
            week = local_day // 7
            if name == "app_opened":
                load = (
                    median_load
                    * math.exp(0.5 * self.py.gauss(0, 1))
                    * (1.4 if props["first"] else 1)
                )
                emit(
                    t,
                    name,
                    {
                        "is_first_open": opens == 0,
                        "load_ms": int(load),
                        "referrer_type": _pick(
                            self.py, FIRST_REFERRER if props["first"] else RETURN_REFERRER
                        ),
                        "current_streak_days": streak(local_day),
                    },
                )
                opens += 1
                if summary_week != week:
                    returning = summary_week is not None and days
                    summary_week = week
                    if returning:
                        sprints, minutes = weeks.get(week - 1, (0, 0))
                        emit(
                            t + 0.5,
                            "weekly_summary_viewed",
                            {
                                "sessions_completed_week": sprints,
                                "focus_minutes_week": minutes,
                                "opened_by": "new_week",
                            },
                        )
            elif name == "session_started":
                starts += 1
                emit(t, name, {**props, "session_number": starts})
            elif name == "session_completed":
                first_completion = not days
                days.add(local_day)
                run, ahead = streak(local_day), local_day + 1
                while ahead in days:
                    run, ahead = run + 1, ahead + 1
                longest = max(longest, run)
                totals = weeks.setdefault(week, [0, 0])
                totals[0] += 1
                totals[1] += props["planned_minutes"]
                emit(
                    t,
                    name,
                    {
                        **props,
                        "current_streak_days": streak(local_day),
                        "is_first_completion": first_completion,
                    },
                )
            elif name == "streak_viewed":
                emit(
                    t,
                    name,
                    {
                        **props,
                        "current_streak_days": streak(local_day),
                        "longest_streak_days": longest,
                    },
                )
            elif name == "weekly_summary_viewed":
                sprints, minutes = weeks.get(week, (0, 0))
                emit(
                    t,
                    name,
                    {
                        "sessions_completed_week": sprints,
                        "focus_minutes_week": minutes,
                        **props,
                    },
                )
            elif name == "experiment_exposed":
                emit(t, name, {"experiment_key": exp.key})
            else:
                emit(t, name, props)
        return rows
