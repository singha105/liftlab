"""EXP-000's charts, light and dark, in the same style as the proof charts.

Every chart carries its readout's label, so the Cookie Cats charts say REAL.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from liftlab import cookie_cats, readout
from liftlab import proof_charts as pc
from liftlab.cookie_cats import CookieCats

plt = pc.plt


def save_cookie_cats(
    result: CookieCats, users: pd.DataFrame, out_dir: Path, config: dict | None = None
) -> list[Path]:
    config = config or readout.load_config(cookie_cats.CONFIG)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for stem, draw in (("exp-000-retention", _retention), ("exp-000-gamerounds", _rounds)):
        for mode, theme in pc.THEMES.items():
            fig, ax = pc._figure(theme)
            title, subtitle = draw(ax, result, users, theme, config)
            pc._finish(fig, ax, theme, title, subtitle, label=result.readout.label)
            path = out_dir / f"{stem}-{mode}.png"
            fig.savefig(path, dpi=150, facecolor=theme["surface"])
            plt.close(fig)
            written.append(path)
    return written


def _retention(
    ax, result: CookieCats, users: pd.DataFrame, theme: dict, config: dict
) -> tuple[str, str]:
    r = result.readout
    metrics = [m for m in (r.primary, *r.secondaries) if m.type == "proportion"]
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=theme["grid"], linewidth=0.8)
    left, right = -2.0, 1.4
    for row, m in enumerate(metrics):
        y = len(metrics) - 1 - row
        c = m.comparison
        boot = next(b.diff for b in m.bootstraps if b.statistic == "mean")
        for offset, ci, color, name in (
            (0.1, c.ci, theme["one"], "z-test, 95% Wald interval"),
            (-0.1, boot.ci, theme["two"], "Bootstrap, 95% percentile interval"),
        ):
            low, high = np.array(ci) * 100
            ax.plot([low, high], [y + offset] * 2, color=color, linewidth=2, label=name)
            ax.plot(
                c.diff * 100, y + offset, "o", color=color, markersize=8,
                markeredgecolor=theme["surface"], markeredgewidth=2,
            )  # fmt: skip
        role = "primary" if m is r.primary else "secondary"
        ax.text(
            left + 0.03, y + 0.3, f"{m.name} ({role}): {c.diff * 100:+.2f}pp, "
            f"p = {c.p_value:.4f}", color=theme["ink"], fontsize=10,
            bbox={"facecolor": theme["surface"], "edgecolor": "none", "pad": 1},
        )  # fmt: skip
    mde = config["primary"]["mde"] * 100
    ax.axvline(0, color=theme["ink"], linewidth=1.2)
    for edge in (-mde, mde):
        ax.axvline(edge, color=theme["muted"], linestyle=(0, (4, 3)), linewidth=1.2)
    ax.annotate(
        f"MDE ±{mde:.1f}pp", (mde, -0.75), xytext=(4, 0), textcoords="offset points",
        va="center", color=theme["muted"], fontsize=9,
    )  # fmt: skip
    ax.set_yticks([])
    ax.set_ylim(-1.0, len(metrics) - 0.45)
    ax.set_xlim(left, right)
    ax.set_xlabel("gate_40 − gate_30, percentage points")
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles[:2], labels[:2], loc="lower left", frameon=False)
    c = r.primary.comparison
    return (
        "Moving the gate to level 40 lowered 7-day retention",
        f"{c.control:.2%} to {c.test:.2%}, {c.diff * 100:+.2f}pp (95% CI {c.ci[0] * 100:+.2f} "
        f"to {c.ci[1] * 100:+.2f}). 1-day retention: not significant after Holm.",
    )


def _rounds(
    ax, result: CookieCats, users: pd.DataFrame, theme: dict, config: dict
) -> tuple[str, str]:
    o = result.outliers
    ends = {}
    for arm, color in ((config["control"], theme["one"]), (config["treatment"], theme["two"])):
        rounds = np.sort(users.loc[users["variant"] == arm, "sum_gamerounds"].to_numpy())
        rounds = rounds[rounds > 0]
        share = 1 - np.arange(len(rounds)) / len(rounds)  # at least this many rounds
        ax.step(rounds, share, where="post", color=color, linewidth=2, label=arm)
        ends[arm] = (color, share[-1])
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.axvline(o.cap, color=theme["muted"], linestyle=(0, (4, 3)), linewidth=1.2)
    ax.annotate(
        f"plausibility cap\n{o.cap:,} rounds", (o.cap, 0.3), xytext=(-6, 0),
        textcoords="offset points", ha="right", color=theme["muted"], fontsize=9,
    )  # fmt: skip
    for x in o.outliers:
        color, share = ends[x.variant]
        ax.plot(
            x.rounds, share, "o", color=color, markersize=8,
            markeredgecolor=theme["surface"], markeredgewidth=2,
        )  # fmt: skip
        ax.annotate(
            f"one {x.variant} player:\n{x.rounds:,} rounds,\n{x.rounds_per_day:,.0f} a day",
            (x.rounds, share), xytext=(0, 14), textcoords="offset points", ha="center",
            va="bottom", color=theme["secondary"], fontsize=9,
        )  # fmt: skip
    ax.grid(axis="x", color=theme["grid"], linewidth=0.8)
    ax.set_xlim(1, 2e5)
    ax.set_xlabel("game rounds in the first 14 days (log scale)")
    ax.set_ylabel("share of players with at least that many")
    ax.legend(loc="lower left", frameon=False)
    a, b = o.with_all, o.without
    rounds_metric = next(m for m in result.readout.secondaries if m.type == "mean")
    median = next(x for x in rounds_metric.bootstraps if x.statistic == "median")
    return (
        "Game rounds: a long tail, and one player no person could be",
        f"Mean {a.diff:+.2f} rounds (p = {a.p_value:.2f}) with everyone, {b.diff:+.2f} "
        f"(p = {b.p_value:.2f}) without the player over {o.cap:,}. "
        f"Median {median.control:.0f} to {median.test:.0f}.",
    )
