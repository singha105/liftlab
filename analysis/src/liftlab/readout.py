"""The experiment readout: a pre-registered analysis plan, run in order, ending in a decision.

`build_readout` takes one row per exposed user (the `experiment_users` model) and the
experiment's config, a YAML copy of its pre-registration (docs/experiments/EXP-001.yaml).
It runs the plan in EXP-001's order:

1. sample ratio mismatch against the planned allocation;
2. the primary metric, plus its pre-registered adjustment (CUPED or regression) as a
   sensitivity check that never decides anything;
3. guardrails, judged on their point estimates against their thresholds;
4. secondary metrics, Holm-corrected;

then applies the decision rule top to bottom, and the first rule whose conditions all hold
decides. Users exposed to more than one arm are dropped and counted. Output is Markdown or
JSON, and synthetic data is labeled as such in both.
"""

import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import yaml

from liftlab.stats.bootstrap import bootstrap_ci
from liftlab.stats.cuped import CupedResult, cuped
from liftlab.stats.multiple import holm
from liftlab.stats.srm import SRMResult, srm_check
from liftlab.stats.tests import Comparison, ratio_metric, welch_ttest, ztest_proportions

SYNTHETIC_LABEL = "SYNTHETIC: simulated users with known ground truth, not real usage"
DECISIONS = ("INVALID", "UNDERPOWERED", "KILL", "SHIP", "ITERATE")
METRIC_TYPES = ("proportion", "mean")
GUARDRAIL_TYPES = ("ratio", "quantile")
BOOTSTRAP_RESAMPLES = 1000


@dataclass(frozen=True)
class MetricResult:
    name: str
    type: str
    comparison: Comparison
    holm_p: float | None = None  # secondaries only


@dataclass(frozen=True)
class GuardrailResult:
    name: str
    type: str
    control: float
    test: float
    diff: float  # absolute for a ratio, relative for a quantile
    ci: tuple[float, float]
    threshold: str
    regressed: bool
    detail: str


@dataclass(frozen=True)
class Readout:
    key: str
    name: str
    synthetic: bool
    decision: str
    reasons: tuple[str, ...]
    users: dict[str, int]
    dropped_multiple_arms: int
    required_per_arm: int
    srm: SRMResult
    primary: MetricResult
    adjusted: CupedResult | None
    adjusted_label: str | None
    guardrails: tuple[GuardrailResult, ...]
    secondaries: tuple[MetricResult, ...]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["srm"]["mismatch"] = self.srm.mismatch
        if self.adjusted is not None:
            data["adjusted"]["variance_reduction"] = self.adjusted.variance_reduction
        if self.synthetic:
            data["label"] = SYNTHETIC_LABEL
        return data

    def to_json(self) -> str:
        return json.dumps(_plain(self.to_dict()), indent=2)

    def to_markdown(self) -> str:
        return _markdown(self)


# Config


def load_config(path: Path | str) -> dict:
    config = yaml.safe_load(Path(path).read_text())
    _check_config(config)
    return config


def _check_config(config: dict) -> None:
    for field in ("key", "name", "arms", "control", "treatment", "primary", "decision_rule"):
        if field not in config:
            raise ValueError(f"config is missing '{field}'")
    if set(config["arms"]) != {config["control"], config["treatment"]}:
        raise ValueError("arms must be exactly the control and treatment arms")
    if config["primary"]["type"] not in METRIC_TYPES:
        raise ValueError(f"primary type must be one of {METRIC_TYPES}")
    for metric in config.get("secondary", []):
        if metric["type"] not in METRIC_TYPES:
            raise ValueError(f"secondary type must be one of {METRIC_TYPES}")
    for guardrail in config.get("guardrails", []):
        if guardrail["type"] not in GUARDRAIL_TYPES:
            raise ValueError(f"guardrail type must be one of {GUARDRAIL_TYPES}")
    for rule in config["decision_rule"]:
        if rule["decision"] not in DECISIONS:
            raise ValueError(f"unknown decision {rule['decision']}")
        for condition in rule["when"]:
            if condition not in _CONDITIONS:
                raise ValueError(f"unknown condition {condition}")


# Data


def experiment_users(con: duckdb.DuckDBPyConnection, key: str, source: str) -> pd.DataFrame:
    """Exposed users of one experiment from one source, in exposure order."""
    return con.execute(
        """
        select * from experiment_users
        where experiment_key = ? and source = ?
        order by exposed_at, user_id
        """,
        [key, source],
    ).df()


def at_required_n(users: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Users up to the one who brings the smaller arm to the required N: the planned read.

    `users` should already be the analysis population. If either arm never gets there, all
    of them, and the readout will say UNDERPOWERED.
    """
    n = config["required_per_arm"]
    ordered = users.sort_values(["exposed_at", "user_id"])
    control = (ordered["variant"] == config["control"]).cumsum()
    test = (ordered["variant"] == config["treatment"]).cumsum()
    full = np.flatnonzero((control >= n) & (test >= n))
    return ordered if len(full) == 0 else ordered.iloc[: full[0] + 1]


def population(users: pd.DataFrame, config: dict) -> pd.DataFrame:
    keep = np.ones(len(users), dtype=bool)
    for column in config.get("population", []):
        keep &= users[column].fillna(False).to_numpy(dtype=bool)
    return users[keep]


# The readout


def build_readout(users: pd.DataFrame, config: dict) -> Readout:
    """Run the analysis plan on `users`, the analysis population at the read."""
    _check_config(config)
    alpha = config.get("alpha", 0.05)
    control_arm, treatment_arm = config["control"], config["treatment"]

    multiple = users["variants"] > 1 if "variants" in users else np.zeros(len(users), bool)
    users = users[~multiple]
    in_arms = users["variant"].isin([control_arm, treatment_arm])
    users = users[in_arms]
    arm = (users["variant"] == treatment_arm).to_numpy()
    if arm.sum() < 2 or (~arm).sum() < 2:
        raise ValueError("each arm needs at least two users")

    counts = {control_arm: int((~arm).sum()), treatment_arm: int(arm.sum())}
    srm = srm_check(counts, config["arms"], threshold=config.get("srm_threshold", 0.001))

    primary_config = config["primary"]
    primary = MetricResult(
        primary_config["name"],
        primary_config["type"],
        _compare(users, arm, primary_config, alpha),
    )
    adjusted, adjusted_label = None, None
    if adjustment := primary_config.get("adjustment"):
        y = users[primary_config["column"]].to_numpy(dtype=float)
        adjusted = cuped(y, arm, _covariates(users, adjustment["covariates"]), alpha=alpha)
        adjusted_label = adjustment.get("label", "CUPED")

    guardrails = tuple(_guardrail(users, arm, g, alpha) for g in config.get("guardrails", []))

    secondary_results = [(m, _compare(users, arm, m, alpha)) for m in config.get("secondary", [])]
    corrected = holm([c.p_value for _, c in secondary_results], alpha=alpha).adjusted
    secondaries = tuple(
        MetricResult(m["name"], m["type"], c, p)
        for (m, c), p in zip(secondary_results, corrected, strict=True)
    )

    readout = Readout(
        key=config["key"],
        name=config["name"],
        synthetic=bool("source" in users and (users["source"] == "synthetic").all()),
        decision="",
        reasons=(),
        users=counts,
        dropped_multiple_arms=int(np.asarray(multiple).sum()),
        required_per_arm=config.get("required_per_arm", 0),
        srm=srm,
        primary=primary,
        adjusted=adjusted,
        adjusted_label=adjusted_label,
        guardrails=guardrails,
        secondaries=secondaries,
    )
    decision, reasons = _decide(readout, config)
    return Readout(**{**readout.__dict__, "decision": decision, "reasons": reasons})


def _compare(users: pd.DataFrame, arm: np.ndarray, metric: dict, alpha: float) -> Comparison:
    values = users[metric["column"]].to_numpy(dtype=float)
    if metric["type"] == "proportion":
        return ztest_proportions(
            int(values[~arm].sum()),
            int((~arm).sum()),
            int(values[arm].sum()),
            int(arm.sum()),
            alpha=alpha,
        )
    return welch_ttest(values[~arm], values[arm], alpha=alpha)


def _covariates(users: pd.DataFrame, columns: list[str]) -> np.ndarray:
    """Numeric columns as they are; categories as dummies, dropping the first level."""
    parts = []
    for column in columns:
        values = users[column]
        if pd.api.types.is_numeric_dtype(values) or pd.api.types.is_bool_dtype(values):
            parts.append(values.to_numpy(dtype=float)[:, None])
        else:
            levels = values.fillna("(missing)").astype(str)
            dummies = pd.get_dummies(levels, drop_first=True, dtype=float)
            parts.append(dummies.to_numpy())
    return np.hstack(parts) if parts else np.zeros((len(users), 1))


def _guardrail(users: pd.DataFrame, arm: np.ndarray, g: dict, alpha: float) -> GuardrailResult:
    if g["type"] == "ratio":
        y = users[g["numerator"]].to_numpy(dtype=float)
        x = users[g["denominator"]].to_numpy(dtype=float)
        result = ratio_metric(y[~arm], x[~arm], y[arm], x[arm], alpha=alpha)
        limit = g["max_increase"]
        return GuardrailResult(
            name=g["name"],
            type="ratio",
            control=result.control,
            test=result.test,
            diff=result.diff,
            ci=result.ci,
            threshold=f"{_points(limit)}",
            regressed=result.diff > limit,
            detail=f"test - control {_points(result.diff)} against a limit of {_points(limit)}",
        )

    rows = _padded(users[g["column"]])
    q = g["quantile"]
    control_rows, test_rows = rows[~arm], rows[arm]
    if (
        min(np.isfinite(control_rows).any(axis=1).sum(), np.isfinite(test_rows).any(axis=1).sum())
        < 2
    ):
        return GuardrailResult(
            g["name"],
            "quantile",
            math.nan,
            math.nan,
            math.nan,
            (math.nan, math.nan),
            _quantile_threshold(g),
            False,
            "not enough page loads in one arm to measure",
        )

    def relative(c: np.ndarray, t: np.ndarray) -> np.ndarray:
        def per_resample(rows):
            return np.nanquantile(rows.reshape(len(rows), -1), q, axis=1)

        return per_resample(t) / per_resample(c) - 1

    boot = bootstrap_ci(
        relative,
        control_rows,
        test_rows,
        n_resamples=BOOTSTRAP_RESAMPLES,
        level=1 - alpha,
        seed=0,
    )
    control_q = float(np.nanquantile(control_rows, q))
    test_q = float(np.nanquantile(test_rows, q))
    over_relative = boot.estimate > g["max_relative_increase"]
    over_value = "max_value" in g and test_q > g["max_value"]
    detail = f"test is {boot.estimate:+.1%} against control"
    if "max_value" in g:
        detail += f", and {test_q:,.0f} ms against a cap of {g['max_value']:,} ms"
    return GuardrailResult(
        name=g["name"],
        type="quantile",
        control=control_q,
        test=test_q,
        diff=boot.estimate,
        ci=boot.ci,
        threshold=_quantile_threshold(g),
        regressed=bool(over_relative or over_value),
        detail=detail,
    )


def _padded(column: pd.Series) -> np.ndarray:
    """One row per user, their values left-aligned and padded with NaN."""
    lists = [np.asarray(v if v is not None else [], dtype=float) for v in column]
    width = max((len(v) for v in lists), default=0) or 1
    rows = np.full((len(lists), width), np.nan)
    for i, values in enumerate(lists):
        rows[i, : len(values)] = values
    return rows


def _quantile_threshold(g: dict) -> str:
    text = f"+{g['max_relative_increase']:.0%}"
    return text + (f" or {g['max_value']:,} ms" if "max_value" in g else "")


# The decision rule


def _decide(r: Readout, config: dict) -> tuple[str, tuple[str, ...]]:
    """First rule whose conditions all hold. Reasons record every rule checked on the way."""
    reasons = []
    for rule in config["decision_rule"]:
        checks = [_CONDITIONS[name](r, config) for name in rule["when"]]
        failed = next((text for holds, text in checks if not holds), None)
        if failed is None:
            reasons.extend(text for _, text in checks if text)
            return rule["decision"], tuple(reasons)
        reasons.append(f"Not {rule['decision']}: {failed}")
    raise ValueError("no rule matched; the decision rule needs an 'otherwise' at the end")


def _srm_failed(r: Readout, config: dict) -> tuple[bool, str]:
    p = r.srm.p_value
    if r.srm.mismatch:
        return True, f"sample ratio mismatch, p = {p:.2g} < {r.srm.threshold}"
    return False, f"no sample ratio mismatch ({_p(p)})"


def _below_required_n(r: Readout, config: dict) -> tuple[bool, str]:
    n, smaller = r.required_per_arm, min(r.users.values())
    if smaller < n:
        return True, f"the smaller arm has {smaller:,} users, short of the required {n:,}"
    return False, f"both arms reached {n:,} users"


def _guardrail_regressed(r: Readout, config: dict) -> tuple[bool, str]:
    bad = [g for g in r.guardrails if g.regressed]
    if bad:
        return True, "; ".join(f"{g.name} regressed: {g.detail}" for g in bad)
    return False, "no guardrail regressed beyond its threshold"


def _primary_ci_above_zero(r: Readout, config: dict) -> tuple[bool, str]:
    low, high = r.primary.comparison.ci
    ci = _interval(r.primary, low, high)
    if low > 0:
        return True, f"{r.primary.name} CI {ci} is entirely above 0"
    return False, f"{r.primary.name} CI {ci} includes or is below 0"


def _secondaries_not_below_zero(r: Readout, config: dict) -> tuple[bool, str]:
    worse = [
        m
        for m in r.secondaries
        if m.comparison.diff < 0 and m.holm_p is not None and m.holm_p < m.comparison.alpha
    ]
    if worse:
        names = ", ".join(m.name for m in worse)
        return False, f"secondary metrics significantly worse after Holm: {names}"
    return True, "no secondary metric is significantly worse"


def _primary_at_least_half_mde(r: Readout, config: dict) -> tuple[bool, str]:
    half = config["primary"]["mde"] / 2
    diff = r.primary.comparison.diff
    estimate, target = _value_change(r.primary, diff), _value_change(r.primary, half)
    if diff >= half:
        return (
            True,
            f"{r.primary.name} point estimate {estimate} is at least half the MDE ({target})",
        )
    return False, f"{r.primary.name} point estimate {estimate} is below half the MDE ({target})"


def _otherwise(r: Readout, config: dict) -> tuple[bool, str]:
    return True, ""


_CONDITIONS: dict[str, Callable[[Readout, dict], tuple[bool, str]]] = {
    "srm_failed": _srm_failed,
    "below_required_n": _below_required_n,
    "guardrail_regressed": _guardrail_regressed,
    "primary_ci_above_zero": _primary_ci_above_zero,
    "secondaries_not_below_zero": _secondaries_not_below_zero,
    "primary_at_least_half_mde": _primary_at_least_half_mde,
    "otherwise": _otherwise,
}


# Formatting


def _markdown(r: Readout) -> str:
    control, treatment = list(r.users)
    lines = [f"# {r.name}: {r.decision}", ""]
    if r.synthetic:
        lines += [f"**{SYNTHETIC_LABEL}**", ""]
    srm_state = "MISMATCH" if r.srm.mismatch else "ok"
    lines += [
        f"- **SRM**: {_p(r.srm.p_value)} ({srm_state}) | users {r.users[control]:,} "
        f"{control} / {r.users[treatment]:,} {treatment}"
        + (
            f" | dropped {r.dropped_multiple_arms} seen in both arms"
            if r.dropped_multiple_arms
            else ""
        ),
        f"- **Primary, {r.primary.name}**: {_metric_line(r.primary)}",
    ]
    if r.adjusted is not None:
        a = r.adjusted
        lines.append(
            f"  - {r.adjusted_label}: {_value_change(r.primary, a.estimate)} "
            f"{_interval(r.primary, *a.ci)}, variance {_change(-a.variance_reduction)}"
        )
    for g in r.guardrails:
        lines.append(f"- **Guardrail, {g.name}**: {_guardrail_line(g)}")
    for m in r.secondaries:
        lines.append(f"- **Secondary, {m.name}**: {_metric_line(m)}, Holm-adjusted {_p(m.holm_p)}")
    lines += ["", f"**Decision: {r.decision}**", ""]
    lines += [f"- {reason[0].upper()}{reason[1:]}" for reason in r.reasons]
    if r.synthetic:
        lines += ["", f"*{SYNTHETIC_LABEL}*"]
    return "\n".join(lines) + "\n"


def _metric_line(m: MetricResult) -> str:
    c = m.comparison
    if m.type == "proportion":
        levels = f"{c.control:.1%} → {c.test:.1%}"
    else:
        levels = f"{c.control:.2f} → {c.test:.2f}"
    return (
        f"{levels} | {_value_change(m, c.diff)} {_interval(m, *c.ci)} "
        f"({c.relative:+.1%} relative) | {_p(c.p_value)}"
    )


def _guardrail_line(g: GuardrailResult) -> str:
    state = "REGRESSED" if g.regressed else "ok"
    if g.type == "ratio":
        return (
            f"{g.control:.1%} → {g.test:.1%} | {_points(g.diff)} "
            f"[{_points(g.ci[0])}, {_points(g.ci[1])}] (threshold {g.threshold}) {state}"
        )
    if math.isnan(g.diff):
        return f"{g.detail} (threshold {g.threshold})"
    return (
        f"{g.control:,.0f} → {g.test:,.0f} ms | {g.diff:+.1%} [{g.ci[0]:+.1%}, {g.ci[1]:+.1%}] "
        f"(threshold {g.threshold}) {state}"
    )


def _value_change(m: MetricResult, value: float) -> str:
    return _points(value) if m.type == "proportion" else f"{value:+.2f}"


def _interval(m: MetricResult, low: float, high: float) -> str:
    if m.type == "proportion":
        return f"[{_points(low)}, {_points(high)}]"
    return f"[{low:+.2f}, {high:+.2f}]"


def _change(fraction: float) -> str:
    """A signed percentage that never reads -0%."""
    text = f"{fraction:+.0%}"
    return "±0%" if text in ("+0%", "-0%") else text


def _points(value: float) -> str:
    return f"{value * 100:+.1f}pp"


def _p(p: float | None) -> str:
    """'p = 0.43', 'p = 0.0021' or 'p < 0.0001'."""
    if p is None or math.isnan(p):
        return "p = -"
    return "p < 0.0001" if p < 0.0001 else f"p = {p:.4f}" if p < 0.01 else f"p = {p:.2f}"


def _plain(value):
    """JSON-safe copy: numpy scalars become Python ones, NaN becomes null."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value
