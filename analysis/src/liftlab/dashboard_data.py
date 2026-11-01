"""What the dashboard shows, computed without Streamlit so it can be tested.

Real StudySprint data comes from the local warehouse's `posthog` source, when there is one.
Until then the product pages show Day 3's synthetic run (20,000 users, seed 7), rebuilt in
memory in a few seconds, so the dashboard needs no database file to deploy.
"""

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO

import duckdb
import numpy as np
import pandas as pd

from liftlab import cookie_cats, readout, warehouse
from liftlab.simulate import Experiment, simulate
from liftlab.stats import power as pw

EXP_000_SAVED = warehouse.REPO_DIR / "docs" / "experiments" / "EXP-000-readout.json"
EXP_001_CONFIG = warehouse.REPO_DIR / "docs" / "experiments" / "EXP-001.yaml"
DOCS_IMG = warehouse.REPO_DIR / "docs" / "img"
SYNTHETIC_RUN = {"n_users": 20_000, "seed": 7}  # Day 3's default run
# Day 5's example EXP-001 run: both arms reach 1,377, true activation effect +5.0 points.
EXP_001_RUN = {
    "n_users": 3581,
    "seed": 4,
    "weeks": 2,
    "experiment": Experiment(key="exp-001", start_day=0, audience="new", activation_effect=0.05),
}
FUNNEL_STEPS = {
    "app_opened": "Opened the app",
    "session_started": "Started a session within 24 h",
    "session_completed": "Completed one within 24 h (activated)",
    "second_session_7d": "Completed another within 7 days",
}
PROOFS = (
    ("stats-aa-pvalues", "A/A test"),
    ("stats-peeking", "Peeking"),
    ("stats-cuped", "CUPED"),
    ("stats-srm", "Sample ratio mismatch"),
    ("stats-power", "Power"),
)


@dataclass(frozen=True)
class Tables:
    label: str  # REAL or SYNTHETIC
    real: bool
    data_end: datetime
    north_star: pd.DataFrame
    funnel: pd.DataFrame
    retention: pd.DataFrame


def synthetic_tables() -> Tables:
    sim = simulate(SYNTHETIC_RUN["n_users"], seed=SYNTHETIC_RUN["seed"])
    con = warehouse.connect(":memory:")
    warehouse.load_events(con, sim.events, source="synthetic", data_end=sim.truth.data_end)
    warehouse.build(con)
    return _tables(con, "synthetic", readout.SYNTHETIC_LABEL)


def real_tables(db: Path = warehouse.DEFAULT_DB) -> Tables | None:
    """The `posthog` source from the local warehouse, or None if there's none (yet)."""
    con = _read_only(db)
    if con is None or not _has_source(con, "posthog"):
        return None
    (users,) = con.execute("select count(*) from dim_users where source = 'posthog'").fetchone()
    label = readout.real_label({}, {"all": int(users)}, "posthog")
    return _tables(con, "posthog", label)


def _tables(con: duckdb.DuckDBPyConnection, source: str, label: str) -> Tables:
    def table(name: str, order: str) -> pd.DataFrame:
        return con.execute(f"select * from {name} where source = ? order by {order}", [source]).df()

    (data_end,) = con.execute(
        "select data_end from warehouse_meta where source = ?", [source]
    ).fetchone()
    return Tables(
        label=label,
        real=source != "synthetic",
        data_end=data_end,
        north_star=table("north_star_weekly", "week_start"),
        funnel=table("funnel_activation", "step_number"),
        retention=table("retention_cohorts", "cohort_week"),
    )


def _read_only(db: Path) -> duckdb.DuckDBPyConnection | None:
    if not Path(db).exists():
        return None
    try:
        return duckdb.connect(str(db), read_only=True)
    except duckdb.Error:  # locked by a running `liftlab` command
        return None


def _has_source(con: duckdb.DuckDBPyConnection, source: str) -> bool:
    try:
        return bool(
            con.execute(
                "select count(*) from warehouse_meta where source = ?", [source]
            ).fetchone()[0]
        )
    except duckdb.Error:
        return False


def biggest_drop(funnel: pd.DataFrame) -> pd.Series:
    """The step that loses the most users from the one before it."""
    return funnel.loc[funnel["drop_off"].idxmax()]


def latest_week(north_star: pd.DataFrame, column: str) -> tuple[pd.Timestamp, float, float | None]:
    """The last complete week with a value, that value, and the week before's."""
    known = north_star[north_star[column].notna()]
    last = known.iloc[-1]
    previous = known.iloc[-2][column] if len(known) > 1 else None
    return last["week_start"], float(last[column]), previous


# Experiments


def exp_000(source: Path | str | IO | None = None) -> dict:
    """EXP-000's readout as a dict: computed from the CSV when there is one, otherwise the
    saved readout (aggregates only), so a deployed dashboard works without the Kaggle file."""
    path = source if source is not None else cookie_cats.DEFAULT_CSV
    if isinstance(path, str | Path) and not Path(path).exists():
        saved = json.loads(EXP_000_SAVED.read_text())
        return {**saved, "computed_from": "saved"}
    result = cookie_cats.read(cookie_cats.load(path))
    return {**result.to_dict(), "computed_from": "csv"}


def exp_001_synthetic() -> dict:
    sim = simulate(
        EXP_001_RUN["n_users"],
        seed=EXP_001_RUN["seed"],
        weeks=EXP_001_RUN["weeks"],
        experiment=EXP_001_RUN["experiment"],
    )
    con = warehouse.connect(":memory:")
    warehouse.load_events(con, sim.events, source="synthetic", data_end=sim.truth.data_end)
    warehouse.build(con)
    config = readout.load_config(EXP_001_CONFIG)
    users = readout.experiment_users(con, "exp-001", "synthetic")
    analyzed = readout.at_required_n(readout.population(users, config), config)
    data = readout.build_readout(analyzed, config).to_dict()
    data["truth"] = {
        "activation_effect": EXP_001_RUN["experiment"].activation_effect,
        "control_activation": sim.truth.activation_rate,
    }
    return data


def exp_001_real(db: Path = warehouse.DEFAULT_DB) -> dict:
    config = readout.load_config(EXP_001_CONFIG)
    con = _read_only(db)
    if con is not None and _has_source(con, "posthog"):
        users = readout.population(readout.experiment_users(con, "exp-001", "posthog"), config)
    else:
        users = pd.DataFrame({"variant": pd.Series(dtype=str)})
    return readout.interim(users, config, "posthog").to_dict()


# Any CSV


def metric_type(values: pd.Series) -> str:
    """'proportion' for true/false or 0/1 columns, 'mean' for other numbers."""
    values = _flags_or_numbers(values)
    if pd.api.types.is_bool_dtype(values) or values.isin([0, 1]).all():
        return "proportion"
    return "mean"


def _flags_or_numbers(values: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(values) or pd.api.types.is_numeric_dtype(values):
        return values
    text = values.astype(str).str.strip().str.lower()
    if text.isin(["true", "false"]).all():
        return text == "true"
    numbers = pd.to_numeric(values, errors="coerce")
    if numbers.isna().any():
        raise ValueError(f"{values.name} has values that aren't numbers or true/false")
    return numbers


def upload_users(frame: pd.DataFrame, variant_column: str, metrics: list[str]) -> pd.DataFrame:
    """One row per unit with `variant` and the chosen metric columns, rates as booleans."""
    users = pd.DataFrame(
        {"source": "csv", "variant": frame[variant_column].astype(str), "variants": 1}
    )
    for column in metrics:
        values = _flags_or_numbers(frame[column])
        kind = metric_type(values)
        users[column] = values.astype(bool) if kind == "proportion" else values.astype(float)
    return users


def upload_config(
    users: pd.DataFrame,
    *,
    control: str,
    treatment: str,
    primary: str,
    secondaries: list[str],
    mde: float,
    alpha: float = 0.05,
    power: float = 0.80,
    control_share: float = 0.5,
) -> dict:
    """A readout config for an uploaded CSV: the same rule order as EXP-000 and EXP-001.

    `mde` is absolute: points for a proportion (0.01 is one point), units for a mean. The
    required N comes from the control arm's own rate or mean and sd, so it says whether this
    file could have detected the MDE, not what a plan made beforehand would have said.
    """
    control_values = users.loc[users["variant"] == control, primary].astype(float)
    kind = metric_type(users[primary])
    if kind == "proportion":
        baseline = float(control_values.mean())
        required = pw.sample_size_proportions(
            min(max(baseline, 1e-6), 1 - 1e-6), mde, alpha=alpha, power=power
        )
    else:
        sd = float(control_values.std(ddof=1)) or 1.0
        required = pw.sample_size_means(float(control_values.mean()), sd, mde, alpha=alpha,
                                        power=power)  # fmt: skip

    def metric(column: str) -> dict:
        kind = metric_type(users[column])
        return {
            "name": column,
            "type": kind,
            "column": column,
            "bootstrap": ["mean"] if kind == "proportion" else ["median"],
        }

    return {
        "key": "upload",
        "name": "Uploaded CSV",
        "label": "REAL: uploaded CSV",
        "arms": {control: control_share, treatment: 1 - control_share},
        "control": control,
        "treatment": treatment,
        "alpha": alpha,
        "srm_threshold": 0.001,
        "required_per_arm": required,
        "primary": {**metric(primary), "mde": mde},
        "secondary": [metric(column) for column in secondaries],
        "decision_rule": [
            {"decision": "INVALID", "when": ["srm_failed"]},
            {"decision": "UNDERPOWERED", "when": ["below_required_n"]},
            {"decision": "SHIP", "when": ["primary_ci_above_zero", "secondaries_not_below_zero"]},
            {"decision": "ITERATE", "when": ["primary_at_least_half_mde"]},
            {"decision": "KILL", "when": ["otherwise"]},
        ],
    }


def sample_size(
    baseline: float, mde: float, *, alpha: float, power: float, daily: float
) -> dict[str, float]:
    """Users per arm for a two-sided test of two proportions, and days at `daily` users."""
    n = pw.sample_size_proportions(baseline, mde, alpha=alpha, power=power)
    return {"per_arm": n, "total": 2 * n, "days": pw.duration_days(n, daily) if daily else math.inf}


def proof_numbers() -> dict:
    return json.loads((DOCS_IMG / "stats-proofs.json").read_text())


def proof_captions(numbers: dict) -> dict[str, str]:
    """One line per Day 5 proof chart, with the numbers from stats-proofs.json."""
    aa, peek, cup = numbers["aa"], numbers["peeking"], numbers["cuped"]
    srm, power = numbers["srm"], numbers["power"]
    return {
        "stats-aa-pvalues": (
            f"With no real effect, {aa['rate']:.1%} of {aa['runs']:,} experiments came out "
            "significant against a 5% target, and the p-values are close to flat, as they "
            "should be."
        ),
        "stats-peeking": (
            f"Checking a z-test every day and stopping at the first p < 0.05 gave "
            f"{peek['naive_rate']:.1%} false wins; the mSPRT, built for looking every day, gave "
            f"{peek['msprt_rate']:.1%}."
        ),
        "stats-cuped": (
            f"Adjusting for each user's previous 28 days cut the variance of the estimate by "
            f"{cup['empirical_variance_reduction']:.0%}, with the same answer on average and "
            f"{cup['coverage_cuped']:.1%} coverage."
        ),
        "stats-srm": (
            f"A broken 52/48 split gets caught {srm['flagged']['52%'][0]:.0%} of the time at "
            f"EXP-001's {srm['sizes'][0]:,} users and {srm['flagged']['52%'][-1]:.0%} at "
            f"{srm['sizes'][-1]:,}; fair splits were never flagged."
        ),
        "stats-power": (
            f"With a true +{power['true_effect'] * 100:.0f}-point lift at the planned N, "
            f"{power['rate']:.1%} of experiments detected it, against "
            f"{power['expected']:.1%} expected."
        ),
    }


def interval_rows(data: dict) -> pd.DataFrame:
    """Every metric and guardrail of a readout dict as rows for an interval chart, test −
    control in its own unit: points for rates, the metric's units for means."""
    rows = []
    metrics = [("Primary", data["primary"])]
    metrics += [("Secondary", m) for m in data.get("secondaries", [])]
    for role, m in metrics:
        c = m["comparison"]
        scale = 100 if m["type"] == "proportion" else 1
        rows.append(
            {
                "role": role,
                "metric": m["name"],
                "unit": "pp" if scale == 100 else "",
                "method": c["method"],
                "control": c["control"],
                "test": c["test"],
                "diff": c["diff"] * scale,
                "low": c["ci"][0] * scale,
                "high": c["ci"][1] * scale,
                "p_value": c["p_value"],
            }
        )
        for b in m.get("bootstraps", []):
            rows.append(
                {
                    "role": role,
                    "metric": m["name"],
                    "unit": "pp" if scale == 100 else "",
                    "method": f"Bootstrap, {b['statistic']}",
                    "control": b["control"],
                    "test": b["test"],
                    "diff": b["diff"]["estimate"] * scale,
                    "low": b["diff"]["ci"][0] * scale,
                    "high": b["diff"]["ci"][1] * scale,
                    "p_value": np.nan,
                }
            )
    return pd.DataFrame(rows)
