"""Charts for the simulation proofs, one light and one dark PNG each, for docs/img/.

Two series at most per chart, in the first two slots of a palette checked for color-vision
deficiency in both modes; every chart is labeled SYNTHETIC. matplotlib is a dev dependency,
so it's imported here and nowhere in the library itself.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

from liftlab import proofs  # noqa: E402
from liftlab.readout import SYNTHETIC_LABEL  # noqa: E402

THEMES = {
    "light": {
        "surface": "#fcfcfb", "ink": "#0b0b0b", "secondary": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7", "one": "#2a78d6", "two": "#eb6834",
        "neutral": "#c3c2b7",
    },
    "dark": {
        "surface": "#1a1a19", "ink": "#f0efec", "secondary": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835", "one": "#3987e5", "two": "#d95926",
        "neutral": "#52514e",
    },
}  # fmt: skip


def save_all(results: dict[str, object], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    charts = {
        "aa": ("stats-aa-pvalues", _aa),
        "peeking": ("stats-peeking", _peeking),
        "cuped": ("stats-cuped", _cuped),
        "srm": ("stats-srm", _srm),
        "power": ("stats-power", _power),
    }
    written = []
    for name, result in results.items():
        stem, draw = charts[name]
        for mode, theme in THEMES.items():
            fig, ax = _figure(theme)
            title, subtitle = draw(ax, result, theme)
            _finish(fig, ax, theme, title, subtitle)
            path = out_dir / f"{stem}-{mode}.png"
            fig.savefig(path, dpi=150, facecolor=theme["surface"])
            plt.close(fig)
            written.append(path)
    return written


def _figure(theme: dict):
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
            "font.size": 10,
        }
    )
    fig, ax = plt.subplots(figsize=(8, 4.6))
    fig.patch.set_facecolor(theme["surface"])
    ax.set_facecolor(theme["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(theme["axis"])
    ax.tick_params(colors=theme["muted"], length=0, pad=6)
    ax.grid(axis="y", color=theme["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    return fig, ax


def _finish(fig, ax, theme: dict, title: str, subtitle: str) -> None:
    for label in (ax.xaxis.label, ax.yaxis.label):
        label.set_color(theme["secondary"])
    fig.subplots_adjust(left=0.09, right=0.84, top=0.80, bottom=0.17)
    fig.text(0.09, 0.93, title, color=theme["ink"], fontsize=13, fontweight="bold")
    fig.text(0.09, 0.875, subtitle, color=theme["secondary"], fontsize=10)
    fig.text(0.09, 0.03, SYNTHETIC_LABEL, color=theme["muted"], fontsize=8.5)
    legend = ax.get_legend()
    if legend:
        legend.get_frame().set_alpha(0)
        for text in legend.get_texts():
            text.set_color(theme["secondary"])


def _end_label(ax, x: float, y: float, text: str, theme: dict) -> None:
    ax.annotate(
        text,
        (x, y),
        xytext=(8, 0),
        textcoords="offset points",
        va="center",
        color=theme["secondary"],
        fontsize=9.5,
        annotation_clip=False,
    )


def _pct(value: float) -> str:
    return f"{value:.1%}"


def _aa(ax, r: "proofs.FixedHorizon", theme: dict) -> tuple[str, str]:
    bins = np.linspace(0, 1, 21)
    ax.hist(r.p_values, bins=bins, color=theme["one"], edgecolor=theme["surface"], linewidth=2)
    per_bin = r.runs / 20
    ax.axhline(per_bin, color=theme["muted"], linestyle=(0, (4, 3)), linewidth=1.2)
    _end_label(ax, 1.0, per_bin, f"flat: {per_bin:g} per bin", theme)
    ax.set_xlim(0, 1)
    ax.set_xlabel("p-value of the two-proportion z-test")
    ax.set_ylabel("experiments")
    low, high = r.rate_ci
    return (
        f"A/A: {r.runs:,} experiments with no effect",
        f"False-positive rate {_pct(r.rate)} (95% CI {_pct(low)} to {_pct(high)}), "
        f"target 5%. p-values should be flat.",
    )


def _peeking(ax, r: "proofs.Peeking", theme: dict) -> tuple[str, str]:
    days = np.arange(1, r.looks + 1)
    ax.plot(days, r.naive_by_day, color=theme["two"], linewidth=2, label="Fixed-horizon z-test")
    ax.plot(days, r.msprt_by_day, color=theme["one"], linewidth=2, label="mSPRT")
    ax.axhline(proofs.ALPHA, color=theme["muted"], linestyle=(0, (4, 3)), linewidth=1.2)
    _end_label(ax, r.looks, r.naive_by_day[-1], f"z-test {_pct(r.naive_rate)}", theme)
    _end_label(ax, r.looks, r.msprt_by_day[-1], f"mSPRT {_pct(r.msprt_rate)}", theme)
    ax.annotate(
        "5% target",
        (r.looks / 2, proofs.ALPHA),
        xytext=(0, 4),
        textcoords="offset points",
        color=theme["muted"],
        fontsize=9,
    )
    ax.set_xlim(1, r.looks)
    ax.set_ylim(0, max(r.naive_by_day) * 1.15)
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_xlabel("daily look (look 1 comes once day 1's 24-hour activation windows close)")
    ax.set_ylabel("share stopped for a false win")
    ax.legend(loc="upper left", frameon=False)
    return (
        f"Peeking: {r.runs:,} A/A experiments, checked daily for {r.looks} days",
        f"Stopping at the first p < 0.05: {_pct(r.naive_rate)} false positives. "
        f"mSPRT: {_pct(r.msprt_rate)}.",
    )


def _cuped(ax, r: "proofs.CupedProof", theme: dict) -> tuple[str, str]:
    raw, adj = np.array(r.raw_estimates), np.array(r.cuped_estimates)
    edge = np.quantile(np.abs(raw), 0.995)
    bins = np.linspace(-edge, edge, 41)
    ax.hist(raw, bins=bins, histtype="step", color=theme["two"], linewidth=2, label="Unadjusted")
    ax.hist(adj, bins=bins, histtype="step", color=theme["one"], linewidth=2, label="CUPED")
    ax.axvline(0, color=theme["muted"], linestyle=(0, (4, 3)), linewidth=1.2)
    ax.set_xlabel("estimated difference in completed sessions per user in 7 days (truth: 0)")
    ax.set_ylabel("experiments")
    ax.legend(loc="upper right", frameon=False)
    return (
        f"CUPED: the same {r.runs:,} A/A experiments, adjusted and not",
        f"Variance down {r.empirical_variance_reduction:.0%} across experiments "
        f"({r.variance_reduction:.0%} as reported), confidence intervals "
        f"{r.ci_width_reduction:.0%} narrower.",
    )


def _srm(ax, r: "proofs.SRMProof", theme: dict) -> tuple[str, str]:
    sizes = np.array(r.sizes)
    curve = np.linspace(1000, sizes.max() * 1.05, 200)
    ax.plot(
        curve,
        [proofs.srm_power(n, 0.52) for n in curve],
        color=theme["two"],
        linewidth=1.2,
        linestyle=(0, (4, 3)),
        label="52/48, theory",
    )
    ax.plot(
        sizes,
        r.flagged["52%"],
        color=theme["two"],
        linewidth=0,
        marker="o",
        markersize=8,
        markeredgecolor=theme["surface"],
        markeredgewidth=2,
        label="52/48, simulated",
    )
    ax.plot(
        sizes,
        r.flagged["50%"],
        color=theme["one"],
        linewidth=2,
        marker="o",
        markersize=8,
        markeredgecolor=theme["surface"],
        markeredgewidth=2,
        label="50/50, simulated",
    )
    exp_n = sizes[0]
    ax.axvline(exp_n, color=theme["muted"], linestyle=(0, (1, 3)), linewidth=1.2)
    ax.annotate(
        f"EXP-001's N\n({exp_n:,} users)",
        (exp_n, 0.55),
        xytext=(6, 0),
        textcoords="offset points",
        color=theme["muted"],
        fontsize=9,
    )
    ax.set_ylim(-0.02, 1.05)
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_xlabel("exposed users in the experiment")
    ax.set_ylabel("share flagged as SRM (p < 0.001)")
    ax.legend(loc="center right", frameon=False)
    flagged_52, clean = r.flagged["52%"], r.flagged["50%"]
    return (
        f"SRM: a 52/48 split against a planned 50/50, {r.runs:,} experiments per point",
        f"Caught {_pct(flagged_52[-1])} of the time at {sizes[-1]:,} users but "
        f"{_pct(flagged_52[0])} at {exp_n:,}. Fair splits flagged: "
        f"{', '.join(_pct(v) for v in clean)}.",
    )


def _power(ax, r: "proofs.FixedHorizon", theme: dict) -> tuple[str, str]:
    diffs = np.array(r.diffs) * 100
    detected = np.array(r.p_values) < proofs.ALPHA
    bins = np.arange(np.floor(diffs.min()), np.ceil(diffs.max()) + 0.5, 0.5)
    ax.hist(
        [diffs[detected], diffs[~detected]],
        bins=bins,
        stacked=True,
        color=[theme["one"], theme["neutral"]],
        edgecolor=theme["surface"],
        linewidth=1.5,
        label=["Detected (p < 0.05)", "Not detected"],
    )
    ax.set_ylim(0, ax.get_ylim()[1] * 1.12)  # room for the label above the tallest bar
    ax.axvline(r.true_effect * 100, color=theme["ink"], linewidth=1.2)
    ax.annotate(
        f"true effect +{r.true_effect * 100:.1f}pp",
        (r.true_effect * 100, 1),
        xycoords=("data", "axes fraction"),
        xytext=(6, -12),
        textcoords="offset points",
        color=theme["secondary"],
        fontsize=9,
    )
    ax.set_xlabel("estimated lift in activation, test - control (percentage points)")
    ax.set_ylabel("experiments")
    ax.legend(loc="upper left", frameon=False)
    low, high = r.rate_ci
    return (
        f"Power: {r.runs:,} experiments with a true +{r.true_effect * 100:.1f}-point lift, "
        f"{proofs.N_PER_ARM:,} users per arm",
        f"Detected {_pct(r.rate)} (95% CI {_pct(low)} to {_pct(high)}), "
        f"expected {_pct(r.expected)}.",
    )
