"""Streamlit pieces shared by the dashboard's pages: badges, charts and the readout view.

Charts are Altair in the same palette as the PNGs, picked by the viewer's light or dark
theme, with tooltips on every mark. Data loaders are cached for the session's server.
"""

import io

import altair as alt
import pandas as pd
import streamlit as st

from liftlab import dashboard_data as dd
from liftlab.palette import SEQUENTIAL, THEMES

FONT = "Source Sans Pro, sans-serif"


def mode() -> str:
    theme = getattr(st.context, "theme", None)
    return "dark" if getattr(theme, "type", None) == "dark" else "light"


def colors() -> dict[str, str]:
    return THEMES[mode()]


def badge(label: str) -> None:
    """The page's REAL or SYNTHETIC badge, with the full label beside it."""
    kind, _, rest = label.partition(": ")
    st.badge(kind, color="blue" if kind == "REAL" else "violet")
    st.caption(rest)


# Cached data


@st.cache_data(show_spinner="Building the synthetic warehouse (about 5 seconds)")
def synthetic_tables() -> dd.Tables:
    return dd.synthetic_tables()


@st.cache_data(ttl=300, show_spinner=False)
def real_tables() -> dd.Tables | None:
    return dd.real_tables()


@st.cache_data(show_spinner="Reading 90,189 players and bootstrapping (about 5 seconds)")
def exp_000(csv: bytes | None) -> dict:
    return dd.exp_000(io.BytesIO(csv) if csv is not None else None)


@st.cache_data(show_spinner="Simulating EXP-001")
def exp_001_synthetic() -> dict:
    return dd.exp_001_synthetic()


@st.cache_data(ttl=300, show_spinner=False)
def exp_001_real() -> dict:
    return dd.exp_001_real()


def product_tables() -> dd.Tables:
    """Real StudySprint tables if the warehouse has any (the viewer can switch), else
    synthetic, with a note that there's no real data yet."""
    real = real_tables()
    if real is None:
        st.sidebar.caption(
            "REAL: StudySprint live data, N = 0. The live app isn't sending events yet, "
            "so the product pages show the synthetic run."
        )
        return synthetic_tables()
    pick = st.sidebar.radio("Product data", ["Real", "Synthetic"], horizontal=True)
    return real if pick == "Real" else synthetic_tables()


# Charts


def show(chart: alt.Chart) -> None:
    c = colors()
    styled = (
        chart.configure(background="transparent", font=FONT)
        .configure_view(stroke=None)
        .configure_axis(
            labelColor=c["muted"],
            titleColor=c["secondary"],
            gridColor=c["grid"],
            domainColor=c["axis"],
            tickColor=c["axis"],
            labelFontSize=12,
            titleFontSize=12,
            titleFontWeight="normal",
        )
        .configure_legend(labelColor=c["secondary"], titleColor=c["secondary"], orient="top")
        .configure_title(color=c["ink"], subtitleColor=c["secondary"], anchor="start")
    )
    st.altair_chart(styled, theme=None, width="stretch")


def line(frame: pd.DataFrame, column: str, title: str, fmt: str, height: int = 220) -> None:
    """One series over weeks, with a crosshair and a tooltip."""
    c = colors()
    data = frame[["week_start", column]].dropna()
    base = alt.Chart(data).encode(
        x=alt.X("week_start:T", title=None, axis=alt.Axis(format="%b %d", grid=False)),
        y=alt.Y(f"{column}:Q", title=None, axis=alt.Axis(format=fmt, tickCount=4)),
    )
    hover = alt.selection_point(fields=["week_start"], nearest=True, on="pointerover", empty=False)
    chart = alt.layer(
        base.mark_line(color=c["one"], strokeWidth=2),
        base.mark_point(color=c["one"], filled=True, size=70, stroke=c["surface"], strokeWidth=2)
        .encode(opacity=alt.condition(hover, alt.value(1), alt.value(0)))
        .add_params(hover),
        base.mark_rule(color=c["axis"])
        .encode(
            opacity=alt.condition(hover, alt.value(1), alt.value(0)),
            tooltip=[
                alt.Tooltip("week_start:T", title="Week of", format="%Y-%m-%d"),
                alt.Tooltip(f"{column}:Q", title=title, format=fmt),
            ],
        )
        .transform_filter(hover),
    ).properties(title=title, height=height)
    show(chart)


def funnel(frame: pd.DataFrame) -> None:
    c = colors()
    worst = dd.biggest_drop(frame)["step"]
    data = frame.assign(
        label=frame["step"].map(dd.FUNNEL_STEPS),
        highlight=frame["step"] == worst,
        text=[
            f"{u:,}  ({o:.0%})"
            for u, o in zip(frame["users"], frame["overall_conversion"], strict=True)
        ],
    )
    order = list(data["label"])
    y = alt.Y("label:N", sort=order, title=None, axis=alt.Axis(labelLimit=260))
    bars = (
        alt.Chart(data)
        .mark_bar(cornerRadiusEnd=4, height=28)
        .encode(
            x=alt.X("users:Q", title="new users with 7 full days of data"),
            y=y,
            color=alt.condition(alt.datum.highlight, alt.value(c["two"]), alt.value(c["neutral"])),
            tooltip=[
                alt.Tooltip("label:N", title="Step"),
                alt.Tooltip("users:Q", title="Users", format=","),
                alt.Tooltip("step_conversion:Q", title="From the step before", format=".1%"),
                alt.Tooltip("overall_conversion:Q", title="Of everyone", format=".1%"),
                alt.Tooltip("drop_off:Q", title="Lost at this step", format=","),
            ],
        )
    )
    text = (
        alt.Chart(data)
        .mark_text(align="left", dx=6, color=c["secondary"], fontSize=12)
        .encode(x="users:Q", y=y, text="text:N")
    )
    show((bars + text).properties(height=230))


def retention_heatmap(frame: pd.DataFrame) -> None:
    c, (low, high) = colors(), SEQUENTIAL[mode()]
    long = frame.melt(
        id_vars=["cohort_week", "cohort_users"],
        value_vars=["d1_retention", "d7_retention", "d28_retention"],
        var_name="day",
        value_name="retention",
    )
    long["day"] = long["day"].str.split("_").str[0].str.upper()
    long["cohort"] = pd.to_datetime(long["cohort_week"]).dt.strftime("%b %d")
    long["text"] = ["not yet" if pd.isna(v) else f"{v:.1%}" for v in long["retention"]]
    cohorts = list(dict.fromkeys(long["cohort"]))
    x = alt.X(
        "day:N", sort=["D1", "D7", "D28"], title=None, axis=alt.Axis(orient="top", labelAngle=0)
    )
    y = alt.Y("cohort:N", sort=cohorts, title="cohort (week of first open)")
    tooltip = [
        alt.Tooltip("cohort_week:T", title="Cohort week", format="%Y-%m-%d"),
        alt.Tooltip("cohort_users:Q", title="New users", format=","),
        alt.Tooltip("day:N", title="Day"),
        alt.Tooltip("text:N", title="Retention"),
    ]
    cells = (
        alt.Chart(long)
        .mark_rect(cornerRadius=4, stroke=c["surface"], strokeWidth=2)
        .encode(
            x=x,
            y=y,
            color=alt.condition(
                "isValid(datum.retention)",
                alt.Color(
                    "retention:Q",
                    scale=alt.Scale(range=[low, high], zero=True),
                    legend=alt.Legend(format=".0%", title="retention"),
                ),
                alt.value(c["grid"]),
            ),
            tooltip=tooltip,
        )
    )
    # Past the middle of the ramp a cell is dark on light and light on dark: surface text.
    middle = float(long["retention"].max()) / 2
    labels = (
        alt.Chart(long)
        .mark_text(fontSize=13)
        .encode(
            x=x,
            y=y,
            text="text:N",
            color=alt.condition(
                f"isValid(datum.retention) && datum.retention > {middle}",
                alt.value(c["surface"]),
                alt.value(c["ink"]),
            ),
            tooltip=tooltip,
        )
    )
    show((cells + labels).properties(height=34 * len(cohorts) + 40))


def intervals(rows: pd.DataFrame, metric: str) -> None:
    """One metric's test − control with every interval the readout computed, and zero."""
    c = colors()
    data = rows[rows["metric"] == metric].reset_index(drop=True)
    data["row"] = -data.index.astype(float)  # first method on top
    unit = data["unit"].iloc[0]
    title = f"test − control ({unit})" if unit else "test − control"
    methods = list(data["method"])
    color = alt.Color(
        "method:N",
        scale=alt.Scale(domain=methods, range=[c["one"], c["two"]][: len(methods)]),
        legend=alt.Legend(title=None),
    )
    y = alt.Y("row:Q", axis=None, scale=alt.Scale(domain=[-len(methods) + 0.4, 0.6]))
    tooltip = [
        alt.Tooltip("method:N", title="Method"),
        alt.Tooltip("diff:Q", title="Estimate", format="+.2f"),
        alt.Tooltip("low:Q", title="95% CI low", format="+.2f"),
        alt.Tooltip("high:Q", title="95% CI high", format="+.2f"),
    ]
    rules = (
        alt.Chart(data)
        .mark_rule(strokeWidth=3)
        .encode(
            x=alt.X("low:Q", title=title, axis=alt.Axis(tickCount=8)),
            x2="high:Q",
            y=y,
            color=color,
            tooltip=tooltip,
        )
    )
    points = alt.Chart(data).mark_point(filled=True, size=110, stroke=c["surface"],
                                        strokeWidth=2, opacity=1).encode(
        x="diff:Q", y=y, color=color, tooltip=tooltip
    )  # fmt: skip
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=c["ink"]).encode(x="x:Q")
    # Streamlit fits the whole chart to this height, title, legend and axis included.
    show((zero + rules + points).properties(title=metric, height=120 + 34 * len(methods)))


# Readouts


def readout(data: dict) -> None:
    """A readout dict (`Readout.to_dict()`, or EXP-000's with its outliers) on the page."""
    badge(data["label"])
    control, treatment = list(data["users"])
    decision = data["decision"] + (f": {data['action']}" if data.get("action") else "")
    with st.container(border=True):
        st.markdown(f"#### Decision: {decision}")
        decisive = [r for r in data["reasons"] if not r.startswith("Not ")]
        st.caption(
            "; ".join(decisive) if decisive else f"No earlier rule matched. {data['reasons'][-1]}"
        )

    srm = data["srm"]
    cols = st.columns(3)
    cols[0].metric(f"Users, {control}", f"{data['users'][control]:,}")
    cols[1].metric(f"Users, {treatment}", f"{data['users'][treatment]:,}")
    cols[2].metric(
        "SRM check", "MISMATCH" if srm["mismatch"] else "passed", f"p = {srm['p_value']:.4f}",
        delta_color="off", delta_arrow="off",
    )  # fmt: skip

    rows = dd.interval_rows(data)
    st.markdown("##### Metrics, test − control")
    st.dataframe(_metric_table(data, rows), hide_index=True, width="stretch")
    for metric in dict.fromkeys(rows["metric"]):
        intervals(rows, metric)

    if data.get("guardrails"):
        st.markdown("##### Guardrails")
        st.dataframe(
            pd.DataFrame(
                {
                    "Guardrail": g["name"],
                    "Result": g["detail"],
                    "Threshold": g["threshold"],
                    "State": "REGRESSED" if g["regressed"] else "ok",
                }
                for g in data["guardrails"]
            ),
            hide_index=True,
            width="stretch",
        )
    with st.expander("How the decision rule got there"):
        for reason in data["reasons"]:
            st.markdown(f"- {reason}")
    st.caption(data["label"])


def _metric_table(data: dict, rows: pd.DataFrame) -> pd.DataFrame:
    holm = {m["name"]: m.get("holm_p") for m in data.get("secondaries", [])}

    def level(row) -> str:
        if row["unit"] == "pp" and not row["method"].endswith("median"):
            return f"{row['control']:.2%} → {row['test']:.2%}"
        return f"{row['control']:,.2f} → {row['test']:,.2f}"

    return pd.DataFrame(
        {
            "Metric": rows["metric"],
            "Role": rows["role"],
            "Method": rows["method"],
            "Control → test": [level(r) for _, r in rows.iterrows()],
            "Difference [95% CI]": [
                f"{r['diff']:+.2f}{r['unit']} [{r['low']:+.2f}, {r['high']:+.2f}]"
                for _, r in rows.iterrows()
            ],
            "p": ["" if pd.isna(p) else f"{p:.4f}" for p in rows["p_value"]],
            "Holm p": [
                f"{holm[m]:.4f}" if holm.get(m) is not None and not pd.isna(p) else ""
                for m, p in zip(rows["metric"], rows["p_value"], strict=True)
            ],
        }
    )


def interim(data: dict) -> None:
    badge(data["label"])
    users, need = data["users"], data["required_per_arm"]
    control, treatment = list(users)
    cols = st.columns(3)
    cols[0].metric(f"Exposed, {control}", f"{users[control]:,}", f"of {need:,}", delta_color="off")
    cols[1].metric(
        f"Exposed, {treatment}", f"{users[treatment]:,}", f"of {need:,}", delta_color="off"
    )
    power = data["power_at_mde"]
    cols[2].metric(
        f"Power for +{data['mde'] * 100:.1f}pp", "none yet" if power is None else f"{power:.0%}"
    )
    st.markdown(
        "Underpowered means this read can't be acted on either way. Not significant says almost "
        "nothing about whether Quick Start works, and significant would most likely overstate "
        "the lift, since only large estimates clear the bar at this size. The decision rule "
        "calls any read before the required N UNDERPOWERED."
    )
    if data.get("readout"):
        with st.expander("The read so far"):
            readout(data["readout"])
    st.caption(data["label"])
