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
decides. A metric can also list bootstrap statistics (`mean`, `median`) to report the
difference in that statistic with a percentile interval next to its test. Users exposed to
more than one arm are dropped and counted. Output is Markdown or JSON, and every readout is
labeled REAL or SYNTHETIC in both: real ones with their N, and "underpowered" when an arm is
short of the required N.
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

from liftlab.stats import power as pw
from liftlab.stats.bootstrap import BootstrapResult, bootstrap_ci
from liftlab.stats.cuped import CupedResult, cuped
from liftlab.stats.multiple import holm
from liftlab.stats.srm import SRMResult, srm_check
from liftlab.stats.tests import Comparison, ratio_metric, welch_ttest, ztest_proportions

SYNTHETIC_LABEL = "SYNTHETIC: simulated users with known ground truth, not real usage"
REAL_LABELS = {"posthog": "REAL: StudySprint live data", "csv": "REAL: uploaded CSV"}
DECISIONS = ("INVALID", "UNDERPOWERED", "KILL", "SHIP", "ITERATE")
METRIC_TYPES = ("proportion", "mean")
GUARDRAIL_TYPES = ("proportion", "ratio", "quantile")
BOOTSTRAP_STATISTICS = {
    "mean": lambda values: values.mean(axis=1),
    "median": lambda values: np.median(values, axis=1),
}
BOOTSTRAP_RESAMPLES = 1000


@dataclass(frozen=True)
class BootstrapDiff:
    """Test minus control in one statistic, with a percentile bootstrap interval."""

    statistic: str
    control: float
    test: float
    diff: BootstrapResult


@dataclass(frozen=True)
class MetricResult:
    name: str
    type: str
    comparison: Comparison
    holm_p: float | None = None  # secondaries only
    bootstraps: tuple[BootstrapDiff, ...] = ()


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
    label: str  # REAL or SYNTHETIC, on every output
    decision: str
    action: str | None  # what the decision means for the product, from the config
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
        return data

    def to_json(self) -> str:
        return json.dumps(_plain(self.to_dict()), indent=2)

    def to_markdown(self) -> str:
        return _markdown(self)


@dataclass(frozen=True)
class Interim:
    """The read so far, on however many users there are. Descriptive: it decides nothing.

    The pre-registered rule makes any read before the required N UNDERPOWERED, so this only
    says how far the run has to go and what the current sample could and couldn't detect.
    """

    key: str
    name: str
    label: str
    users: dict[str, int]
    required_per_arm: int
    mde: float
    power_at_mde: float | None  # at the smaller arm's size; None with no users
    mde_at_n: float | None  # detected with 80% power at that size
    readout: Readout | None  # once each arm has two users

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(_plain(self.to_dict()), indent=2)

    def to_markdown(self) -> str:
        return _interim_markdown(self)


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
    for metric in [config["primary"], *config.get("secondary", [])]:
        for statistic in metric.get("bootstrap", []):
            if statistic not in BOOTSTRAP_STATISTICS:
                raise ValueError(f"bootstrap statistics must be in {tuple(BOOTSTRAP_STATISTICS)}")
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


def real_label(config: dict, counts: dict[str, int], source: str | None = None) -> str:
    """'REAL: <what the data is>, N = <users>', plus 'underpowered' if an arm is short."""
    label = config.get("label") or REAL_LABELS.get(source or "", f"REAL: {source} data")
    label += f", N = {sum(counts.values()):,}"
    required = config.get("required_per_arm", 0)
    if min(counts.values(), default=0) < required:
        label += f", underpowered (needs {required:,} per arm)"
    return label


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

    resamples = config.get("bootstrap_resamples", BOOTSTRAP_RESAMPLES)
    primary_config = config["primary"]
    primary = MetricResult(
        primary_config["name"],
        primary_config["type"],
        _compare(users, arm, primary_config, alpha),
        bootstraps=_bootstraps(users, arm, primary_config, alpha, resamples),
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
        MetricResult(m["name"], m["type"], c, p, _bootstraps(users, arm, m, alpha, resamples))
        for (m, c), p in zip(secondary_results, corrected, strict=True)
    )

    sources = users["source"].unique() if "source" in users else []
    synthetic = len(sources) > 0 and all(source == "synthetic" for source in sources)
    readout = Readout(
        key=config["key"],
        name=config["name"],
        synthetic=synthetic,
        label=SYNTHETIC_LABEL
        if synthetic
        else real_label(config, counts, sources[0] if len(sources) == 1 else None),
        decision="",
        action=None,
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
    action = config.get("actions", {}).get(decision)
    return Readout(
        **{**readout.__dict__, "decision": decision, "action": action, "reasons": reasons}
    )


def interim(users: pd.DataFrame, config: dict, source: str | None = None) -> Interim:
    """`users` is the analysis population so far, from `source` (read off the rows if they
    have any). A proportion primary needs a `baseline` for the power figures."""
    _check_config(config)
    control_arm, treatment_arm = config["control"], config["treatment"]
    if "variants" in users:
        users = users[users["variants"] <= 1]
    counts = {arm: int((users["variant"] == arm).sum()) for arm in (control_arm, treatment_arm)}
    smaller = min(counts.values())
    primary = config["primary"]
    power_at_mde = mde_at_n = None
    if smaller > 0 and primary["type"] == "proportion":
        baseline, alpha = primary["baseline"], config.get("alpha", 0.05)
        power_at_mde = pw.power_proportions(baseline, primary["mde"], smaller, alpha=alpha)
        room = 1 - baseline
        # Below a few users per arm, no lift that fits under 100% gets 80% power.
        if pw.power_proportions(baseline, room * 0.999, smaller, alpha=alpha) >= 0.80:
            mde_at_n = pw.mde_proportions(baseline, smaller, alpha=alpha)
    full = build_readout(users, config) if smaller >= 2 else None
    sources = users["source"].unique() if "source" in users else []
    synthetic = len(sources) > 0 and all(source == "synthetic" for source in sources)
    source = sources[0] if len(sources) == 1 else source
    return Interim(
        key=config["key"],
        name=config["name"],
        label=SYNTHETIC_LABEL if synthetic else real_label(config, counts, source),
        users=counts,
        required_per_arm=config.get("required_per_arm", 0),
        mde=primary["mde"],
        power_at_mde=power_at_mde,
        mde_at_n=mde_at_n,
        readout=full,
    )


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


def _bootstraps(
    users: pd.DataFrame, arm: np.ndarray, metric: dict, alpha: float, resamples: int
) -> tuple[BootstrapDiff, ...]:
    values = users[metric["column"]].to_numpy(dtype=float)
    control, test = values[~arm], values[arm]
    results = []
    for name in metric.get("bootstrap", []):
        statistic = BOOTSTRAP_STATISTICS[name]
        diff = bootstrap_ci(
            lambda c, t, statistic=statistic: statistic(t) - statistic(c),
            control,
            test,
            n_resamples=resamples,
            level=1 - alpha,
            seed=0,
        )
        level = [float(statistic(v[None])[0]) for v in (control, test)]
        results.append(BootstrapDiff(name, level[0], level[1], diff))
    return tuple(results)


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
    if g["type"] in ("proportion", "ratio"):
        if g["type"] == "proportion":
            result = _compare(users, arm, g, alpha)
        else:
            y = users[g["numerator"]].to_numpy(dtype=float)
            x = users[g["denominator"]].to_numpy(dtype=float)
            result = ratio_metric(y[~arm], x[~arm], y[arm], x[arm], alpha=alpha)
        limit = g["max_increase"]
        return GuardrailResult(
            name=g["name"],
            type=g["type"],
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

    boot = quantile_change(control_rows, test_rows, q, level=1 - alpha)
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


def quantile_change(
    control_rows: np.ndarray, test_rows: np.ndarray, q: float, *, level: float = 0.95
) -> BootstrapResult:
    """Relative change in a quantile, test / control - 1, bootstrapping users, not values."""

    def relative(c: np.ndarray, t: np.ndarray) -> np.ndarray:
        return _row_quantile(t, q) / _row_quantile(c, q) - 1

    return bootstrap_ci(
        relative, control_rows, test_rows, n_resamples=BOOTSTRAP_RESAMPLES, level=level, seed=0
    )


def quantile_level(rows: np.ndarray, q: float, *, level: float = 0.95) -> BootstrapResult:
    """One arm's quantile, bootstrapping users."""
    return bootstrap_ci(
        lambda r: _row_quantile(r, q), rows, n_resamples=BOOTSTRAP_RESAMPLES, level=level, seed=0
    )


def _row_quantile(resamples: np.ndarray, q: float) -> np.ndarray:
    """The quantile of every value in each resample of padded user rows."""
    return np.nanquantile(resamples.reshape(len(resamples), -1), q, axis=1)


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
    lines = [f"# {r.name}: {r.decision}", "", f"**{r.label}**", ""]
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
        *_bootstrap_lines(r.primary),
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
        lines += _bootstrap_lines(m)
    decision = f"{r.decision}, {r.action}" if r.action else r.decision
    lines += ["", f"**Decision: {decision}**", ""]
    lines += [f"- {reason[0].upper()}{reason[1:]}" for reason in r.reasons]
    lines += ["", f"*{r.label}*"]
    return "\n".join(lines) + "\n"


def _interim_markdown(i: Interim) -> str:
    control, treatment = list(i.users)
    smaller, n = min(i.users.values()), i.required_per_arm
    lines = [f"# {i.name}: interim read, not a decision", "", f"**{i.label}**", ""]
    lines.append(
        f"- **Exposed users**: {i.users[control]:,} {control} / {i.users[treatment]:,} "
        f"{treatment}, against the {n:,} per arm the read needs"
        + (f" ({smaller / n:.0%} of the way)" if n and smaller else "")
    )
    mde = _points(i.mde)
    if i.power_at_mde is None:
        lines.append(f"- **Power**: none yet; with no users the test can't detect {mde}.")
    else:
        detects = (
            f"the smallest lift it would catch 80% of the time is {_points(i.mde_at_n)}"
            if i.mde_at_n is not None
            else "no lift that fits under 100% would be caught 80% of the time"
        )
        lines.append(
            f"- **Power**: with {smaller:,} per arm the test detects the planned {mde} "
            f"{i.power_at_mde:.0%} of the time; {detects}."
        )
    lines += [
        "",
        "Underpowered means a result here can't be acted on either way. Not significant says "
        "almost nothing about whether the change works, and significant would most likely "
        "overstate the lift, since only large estimates clear the bar at this size. The "
        "decision rule calls any read before the required N UNDERPOWERED.",
    ]
    if i.readout is not None:
        body = i.readout.to_markdown().rstrip("\n").split("\n")[4:-2]
        lines += ["", "## The read so far", "", *body]
    lines += ["", f"*{i.label}*"]
    return "\n".join(lines) + "\n"


def _bootstrap_lines(m: MetricResult) -> list[str]:
    lines = []
    for b in m.bootstraps:
        if m.type == "proportion" and b.statistic == "mean":
            levels = f"{b.control:.1%} → {b.test:.1%}"
        else:
            levels = f"{b.control:.2f} → {b.test:.2f}"
        lines.append(
            f"  - Bootstrap, difference in {b.statistic}s: {levels} | "
            f"{_value_change(m, b.diff.estimate)} {_interval(m, *b.diff.ci)} "
            f"({b.diff.n_resamples:,} resamples of users)"
        )
    return lines


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
    if g.type in ("proportion", "ratio"):
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
