"""EXP-000: the public Cookie Cats A/B test, read with the same readout as EXP-001.

Cookie Cats is a mobile puzzle game. Its players were randomized at install to a first gate
at level 30 (`gate_30`, the game as it shipped) or level 40 (`gate_40`). The file has one row
per player, so there are no events to rebuild: `load` turns it into the readout's
one-row-per-user shape and `read` runs the plan in docs/experiments/EXP-000.yaml.

Nobody is dropped. Players with more game rounds than the plan's plausibility cap are listed,
and the game-rounds test is rerun without them, as a sensitivity check that decides nothing.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO

import numpy as np
import pandas as pd

from liftlab import readout, warehouse
from liftlab.stats.tests import Comparison, welch_ttest

CONFIG = warehouse.REPO_DIR / "docs" / "experiments" / "EXP-000.yaml"
DEFAULT_CSV = warehouse.REPO_DIR / "data" / "raw" / "cookie_cats.csv"
KAGGLE_URL = "https://www.kaggle.com/datasets/yufengsui/mobile-games-ab-testing"
COLUMNS = ("userid", "version", "sum_gamerounds", "retention_1", "retention_7")
ROUNDS_DAYS = 14  # sum_gamerounds counts the first 14 days after install


@dataclass(frozen=True)
class Outlier:
    user_id: int
    variant: str
    rounds: int
    rounds_per_day: float
    retention_1: bool
    retention_7: bool


@dataclass(frozen=True)
class OutlierCheck:
    cap: int
    outliers: tuple[Outlier, ...]
    largest_below_cap: int
    p99: float
    p999: float
    with_all: Comparison  # the analysis of record, Welch on everyone
    without: Comparison  # sensitivity only


@dataclass(frozen=True)
class CookieCats:
    readout: readout.Readout
    outliers: OutlierCheck

    def to_dict(self) -> dict:
        return {**self.readout.to_dict(), "outliers": asdict(self.outliers)}

    def to_json(self) -> str:
        return json.dumps(readout._plain(self.to_dict()), indent=2)

    def to_markdown(self) -> str:
        return _markdown(self)


def load(source: Path | str | IO) -> pd.DataFrame:
    """The Kaggle CSV as one row per player, in the readout's column names."""
    frame = pd.read_csv(source)
    missing = [column for column in COLUMNS if column not in frame]
    if missing:
        raise ValueError(f"not the Cookie Cats file: missing {', '.join(missing)}")
    if frame["userid"].duplicated().any():
        raise ValueError("a player appears more than once")
    rounds = frame["sum_gamerounds"].astype(int)
    return pd.DataFrame(
        {
            "source": "cookie_cats",
            "user_id": frame["userid"].astype(int),
            "variant": frame["version"].astype(str),
            "variants": 1,
            "retention_1": _flag(frame["retention_1"]),
            "retention_7": _flag(frame["retention_7"]),
            "sum_gamerounds": rounds,
            "no_rounds": rounds == 0,
        }
    )


def read(users: pd.DataFrame, config: dict | None = None) -> CookieCats:
    config = config or readout.load_config(CONFIG)
    return CookieCats(readout.build_readout(users, config), check_outliers(users, config))


def check_outliers(users: pd.DataFrame, config: dict) -> OutlierCheck:
    cap = config["plausible_rounds_cap"]
    rounds = users["sum_gamerounds"].to_numpy()
    over = users[rounds > cap].sort_values("sum_gamerounds", ascending=False)
    kept = users[rounds <= cap]
    return OutlierCheck(
        cap=cap,
        outliers=tuple(
            Outlier(
                user_id=int(row.user_id),
                variant=row.variant,
                rounds=int(row.sum_gamerounds),
                rounds_per_day=row.sum_gamerounds / ROUNDS_DAYS,
                retention_1=bool(row.retention_1),
                retention_7=bool(row.retention_7),
            )
            for row in over.itertuples()
        ),
        largest_below_cap=int(kept["sum_gamerounds"].max()),
        p99=float(np.quantile(rounds, 0.99)),
        p999=float(np.quantile(rounds, 0.999)),
        with_all=_rounds_test(users, config),
        without=_rounds_test(kept, config),
    )


def _rounds_test(users: pd.DataFrame, config: dict) -> Comparison:
    def arm(name: str) -> np.ndarray:
        return users.loc[users["variant"] == name, "sum_gamerounds"].to_numpy(dtype=float)

    return welch_ttest(arm(config["control"]), arm(config["treatment"]), alpha=config["alpha"])


def _flag(column: pd.Series) -> pd.Series:
    """TRUE/FALSE, True/False or 1/0 as booleans."""
    if pd.api.types.is_bool_dtype(column):
        return column
    text = column.astype(str).str.strip().str.lower()
    if not text.isin(["true", "false", "1", "0"]).all():
        raise ValueError(f"{column.name} must be true/false")
    return text.isin(["true", "1"])


def _markdown(c: CookieCats) -> str:
    o = c.outliers
    lines = c.readout.to_markdown().rstrip("\n").split("\n")
    label = lines.pop()  # the closing label goes back at the very end
    lines += [
        f"## Outliers: game rounds over {o.cap:,}",
        "",
        f"Game rounds have a long tail: the 99th percentile is {o.p99:,.0f} and the 99.9th "
        f"{o.p999:,.0f}. {len(o.outliers)} player{'s' if len(o.outliers) != 1 else ''} "
        f"went over the {o.cap:,}-round cap; the largest total under it is "
        f"{o.largest_below_cap:,}.",
        "",
    ]
    if o.outliers:
        lines += [
            "| Player | Arm | Rounds in 14 days | Per day | Back on day 1 | Back on day 7 |",
            "|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {x.user_id} | {x.variant} | {x.rounds:,} | {x.rounds_per_day:,.0f} | "
            f"{'yes' if x.retention_1 else 'no'} | {'yes' if x.retention_7 else 'no'} |"
            for x in o.outliers
        ]
        lines.append("")
    a, b = o.with_all, o.without
    lines += [
        "Welch's t-test on game rounds, test − control:",
        "",
        f"- Everyone (analysis of record): {a.control:.2f} → {a.test:.2f}, "
        f"{a.diff:+.2f} [{a.ci[0]:+.2f}, {a.ci[1]:+.2f}], {readout._p(a.p_value)}",
        f"- Without the {len(o.outliers)} over the cap (sensitivity only): "
        f"{b.control:.2f} → {b.test:.2f}, {b.diff:+.2f} [{b.ci[0]:+.2f}, {b.ci[1]:+.2f}], "
        f"{readout._p(b.p_value)}",
        "",
        "## Why there's no CUPED",
        "",
        "Every player was randomized at install, so there's no behavior from before the "
        "experiment to adjust with. Game rounds and 1-day retention are measured after "
        "assignment and can be changed by the gate, so adjusting for them would bias the "
        "estimate. The file has no pre-assignment attribute (device, country, install source) "
        "for a regression adjustment either. The readout is unadjusted.",
        "",
        label,
    ]
    return "\n".join(lines) + "\n"
