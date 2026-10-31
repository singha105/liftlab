"""Weekly checks during a run: EXP-001's analysis plan, step 6, as set out in Amendment 1.

A look every 7 days from launch. SRM is checked on everyone exposed so far, with the read's
chi-square test and threshold. Each guardrail is computed on users whose 7-day window had
closed by the look (exposed at least 8 days earlier) and followed as an mSPRT 95% confidence
sequence over the looks so far. The run stops early only for an SRM failure (INVALID) or a
guardrail whose always-valid interval lies entirely beyond its threshold (KILL). During the
run a point estimate past the threshold isn't enough; at the read it is. The primary metric
is never looked at.

Each guardrail's mixing sd is its own threshold (2.0 points, 10%, 10% of the 2,000 ms cap),
which tunes the test to regressions about the size the guardrail is there to catch.
"""

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from liftlab import readout
from liftlab.stats.sequential import msprt
from liftlab.stats.srm import srm_check
from liftlab.stats.tests import ratio_metric

LOOK_EVERY = timedelta(days=7)
WINDOW = timedelta(days=8)  # 7 days of sessions, plus 24 hours to see how the last ones ended


@dataclass(frozen=True)
class Bound:
    """One guardrail threshold, followed over the looks."""

    guardrail: str
    measure: str
    threshold: float
    unit: str  # "points", "relative" or "ms": how to print it
    mixing_sd: float
    estimates: tuple[float, ...]  # one per look; NaN where an arm was too small to measure
    ci_low: tuple[float, ...]  # the confidence sequence, intersected over the looks so far
    ci_high: tuple[float, ...]

    def crossed(self, look: int) -> bool:
        return self.ci_low[look] > self.threshold


@dataclass(frozen=True)
class Look:
    week: int
    at: datetime
    users: dict[str, int]  # exposed so far
    srm_p: float
    srm_failed: bool
    guardrail_users: dict[str, int]  # with a closed 7-day window


@dataclass(frozen=True)
class Monitor:
    key: str
    name: str
    synthetic: bool
    launch: datetime
    as_of: datetime
    status: str  # CONTINUE, INVALID or KILL
    reasons: tuple[str, ...]
    looks: tuple[Look, ...]  # up to and including the one that stopped the run
    bounds: tuple[Bound, ...]

    def to_dict(self) -> dict:
        data = asdict(self)
        if self.synthetic:
            data["label"] = readout.SYNTHETIC_LABEL
        return data

    def to_json(self) -> str:
        return json.dumps(readout._plain(self.to_dict()), indent=2, default=str)

    def to_markdown(self) -> str:
        return _markdown(self)


def weekly_checks(users: pd.DataFrame, config: dict, as_of: datetime) -> Monitor:
    """Every weekly look from launch up to `as_of`, stopping at the first that stops the run.

    `users` is the experiment's `experiment_users` rows; launch is the config's `launch`, or
    the day of the first exposure.
    """
    readout._check_config(config)
    control_arm, treatment_arm = config["control"], config["treatment"]
    if "variants" in users:
        users = users[users["variants"] <= 1]
    users = readout.population(users, config)
    users = users[users["variant"].isin([control_arm, treatment_arm])]
    exposed = pd.to_datetime(users["exposed_at"])
    launch = pd.Timestamp(config.get("launch") or exposed.min().floor("D")).to_pydatetime()
    weeks = int((pd.Timestamp(as_of) - pd.Timestamp(launch)) / pd.Timedelta(LOOK_EVERY))

    looks, closed = [], []
    for week in range(1, weeks + 1):
        at = launch + week * LOOK_EVERY
        so_far = users[(exposed <= at).to_numpy()]
        counts = _counts(so_far, (control_arm, treatment_arm))
        srm = srm_check(counts, config["arms"], threshold=config.get("srm_threshold", 0.001))
        window = users[(exposed + WINDOW <= at).to_numpy()]
        closed.append(window)
        looks.append(
            Look(
                week=week,
                at=at,
                users=counts,
                srm_p=srm.p_value,
                srm_failed=srm.mismatch,
                guardrail_users=_counts(window, (control_arm, treatment_arm)),
            )
        )

    alpha = config.get("alpha", 0.05)
    bounds = tuple(
        bound
        for g in config.get("guardrails", [])
        for bound in _bounds(closed, g, treatment_arm, alpha)
    )

    status, reasons, stop = "CONTINUE", [], len(looks)
    for i, look in enumerate(looks):
        if look.srm_failed:
            status = "INVALID"
            reasons.append(f"week {look.week}: sample ratio mismatch, p = {look.srm_p:.2g}")
        crossed = [b for b in bounds if b.crossed(i)]
        if crossed and status == "CONTINUE":
            status = "KILL"
        for b in crossed:
            reasons.append(
                f"week {look.week}: {b.guardrail}, {b.measure} is at least "
                f"{_format(b.ci_low[i], b.unit)} (always-valid 95%), past "
                f"{_format(b.threshold, b.unit)}"
            )
        if status != "CONTINUE":
            stop = i + 1
            break
    if status == "CONTINUE":
        reasons.append(
            "no full week since launch yet"
            if not looks
            else "no sample ratio mismatch, and no guardrail's always-valid interval lies "
            "beyond its threshold"
        )

    return Monitor(
        key=config["key"],
        name=config["name"],
        synthetic=bool("source" in users and (users["source"] == "synthetic").all()),
        launch=launch,
        as_of=as_of,
        status=status,
        reasons=tuple(reasons),
        looks=tuple(looks[:stop]),
        bounds=tuple(_truncate(b, stop) for b in bounds),
    )


def _counts(users: pd.DataFrame, arms: tuple[str, str]) -> dict[str, int]:
    return {arm: int((users["variant"] == arm).sum()) for arm in arms}


def _bounds(looks: list[pd.DataFrame], g: dict, treatment_arm: str, alpha: float) -> list[Bound]:
    """The guardrail's thresholds as bounds: estimate and variance at each look, then mSPRT."""
    if g["type"] == "ratio":
        measured = [_ratio_look(users, g, treatment_arm, alpha) for users in looks]
        specs = [("test - control", g["max_increase"], "points", measured)]
    else:
        measured = [_quantile_look(users, g, treatment_arm, alpha) for users in looks]
        specs = [
            ("test / control - 1", g["max_relative_increase"], "relative", [m[0] for m in measured])
        ]
        if "max_value" in g:
            specs.append(("test arm", g["max_value"], "ms", [m[1] for m in measured]))
    bounds = []
    for measure, threshold, unit, per_look in specs:
        mixing_sd = threshold if unit != "ms" else 0.1 * threshold
        bounds.append(_sequence(g["name"], measure, threshold, unit, mixing_sd, per_look, alpha))
    return bounds


def _ratio_look(users, g, treatment_arm, alpha) -> tuple[float, float]:
    arm = (users["variant"] == treatment_arm).to_numpy()
    y = users[g["numerator"]].to_numpy(dtype=float)
    x = users[g["denominator"]].to_numpy(dtype=float)
    if min(arm.sum(), (~arm).sum()) < 2 or min(x[arm].sum(), x[~arm].sum()) == 0:
        return math.nan, math.nan
    result = ratio_metric(y[~arm], x[~arm], y[arm], x[arm], alpha=alpha)
    return result.diff, result.se**2


def _quantile_look(users, g, treatment_arm, alpha) -> tuple[tuple, tuple]:
    arm = (users["variant"] == treatment_arm).to_numpy()
    rows = readout._padded(users[g["column"]]) if len(users) else np.empty((0, 1))
    measured = np.isfinite(rows).any(axis=1)
    if min((measured & arm).sum(), (measured & ~arm).sum()) < 2:
        return (math.nan, math.nan), (math.nan, math.nan)
    change = readout.quantile_change(rows[~arm], rows[arm], g["quantile"], level=1 - alpha)
    level = readout.quantile_level(rows[arm], g["quantile"], level=1 - alpha)
    return (change.estimate, change.se**2), (level.estimate, level.se**2)


def _sequence(name, measure, threshold, unit, mixing_sd, per_look, alpha) -> Bound:
    """mSPRT over the looks that could be measured; earlier ones carry no bound."""
    estimates = [e for e, _ in per_look]
    usable = [i for i, (e, v) in enumerate(per_look) if not math.isnan(e) and v > 0]
    low, high = [-math.inf] * len(per_look), [math.inf] * len(per_look)
    if usable:
        result = msprt(
            [per_look[i][0] for i in usable],
            [per_look[i][1] for i in usable],
            mixing_sd=mixing_sd,
            alpha=alpha,
        )
        for j, i in enumerate(usable):
            low[i], high[i] = result.ci_low[j], result.ci_high[j]
        for i in range(1, len(per_look)):  # a look without data keeps the last interval
            if i not in usable:
                low[i], high[i] = low[i - 1], high[i - 1]
    return Bound(
        guardrail=name,
        measure=measure,
        threshold=threshold,
        unit=unit,
        mixing_sd=mixing_sd,
        estimates=tuple(estimates),
        ci_low=tuple(low),
        ci_high=tuple(high),
    )


def _truncate(b: Bound, stop: int) -> Bound:
    return Bound(
        b.guardrail, b.measure, b.threshold, b.unit, b.mixing_sd,
        b.estimates[:stop], b.ci_low[:stop], b.ci_high[:stop],
    )  # fmt: skip


# Formatting


def _format(value: float, unit: str) -> str:
    if math.isinf(value) or math.isnan(value):
        return "-"
    if unit == "points":
        return readout._points(value)
    if unit == "relative":
        return f"{value:+.1%}"
    return f"{value:,.0f} ms"


def _markdown(m: Monitor) -> str:
    control, treatment = (m.looks[0].users if m.looks else {"control": 0, "test": 0}).keys()
    title = "CONTINUE" if m.status == "CONTINUE" else f"STOP, {m.status}"
    lines = [f"# {m.name}: weekly check, {title}", ""]
    if m.synthetic:
        lines += [f"**{readout.SYNTHETIC_LABEL}**", ""]
    lines += [
        f"Launch {m.launch:%Y-%m-%d}, data through {m.as_of:%Y-%m-%d %H:%M}. The primary "
        "metric isn't looked at before the read. Guardrails show the estimate and its "
        "always-valid 95% interval, on users whose 7-day window has closed.",
        "",
    ]
    if m.looks:
        header = ["Week", "Look", f"Exposed ({control} / {treatment})", "SRM", "Windows closed"]
        header += [
            f"{b.guardrail}: {b.measure} (stop above {_format(b.threshold, b.unit)})"
            for b in m.bounds
        ]
        lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        for i, look in enumerate(m.looks):
            cells = [
                str(look.week),
                f"{look.at:%Y-%m-%d}",
                f"{look.users[control]:,} / {look.users[treatment]:,}",
                readout._p(look.srm_p) + (" MISMATCH" if look.srm_failed else ""),
                f"{look.guardrail_users[control]:,} / {look.guardrail_users[treatment]:,}",
            ]
            for b in m.bounds:
                if math.isnan(b.estimates[i]):
                    cells.append("-")
                    continue
                cells.append(
                    f"{_format(b.estimates[i], b.unit)} [{_format(b.ci_low[i], b.unit)}, "
                    f"{_format(b.ci_high[i], b.unit)}]" + (" STOP" if b.crossed(i) else "")
                )
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    lines += [f"**{title}**", ""]
    lines += [f"- {reason[0].upper()}{reason[1:]}" for reason in m.reasons]
    if m.synthetic:
        lines += ["", f"*{readout.SYNTHETIC_LABEL}*"]
    return "\n".join(lines) + "\n"
