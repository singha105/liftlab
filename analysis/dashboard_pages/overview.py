import streamlit as st

from liftlab import dashboard_data as dd
from liftlab import dashboard_ui as ui

st.title("Overview")
tables = ui.product_tables()
ui.badge(tables.label)
ns = tables.north_star
st.markdown(
    "The North Star is **weekly completed sessions**: focus sessions that ran to the end, "
    f"counted by week. Complete weeks only, through {tables.data_end:%Y-%m-%d}."
)

tiles = [
    ("weekly_completed_sessions", "Weekly completed sessions", "{:,.0f}"),
    ("wau", "Weekly active users", "{:,.0f}"),
    ("sessions_per_active_user", "Sessions per active user", "{:.2f}"),
    ("completion_rate", "Completion rate", "{:.1%}"),
    ("activation_rate", "Activation rate", "{:.1%}"),
]
for col, (column, name, fmt) in zip(st.columns(len(tiles)), tiles, strict=True):
    week, value, previous = dd.latest_week(ns, column)
    change = None if previous is None else value - previous
    delta = None
    if change is not None:
        delta = f"{change * 100:+.1f}pp" if "%" in fmt else fmt.replace("{:", "{:+").format(change)
    flat = delta is not None and delta.lstrip("+-").rstrip("p").strip("0.,") == ""
    col.metric(
        name,
        fmt.format(value),
        delta.lstrip("+-") if flat else delta,
        delta_color="off" if flat else "normal",
        delta_arrow="off" if flat else "auto",
        help=f"Week of {week:%Y-%m-%d}, against the week before",
    )

ui.line(ns, "weekly_completed_sessions", "Weekly completed sessions (North Star)", ",.0f", 260)

st.markdown("##### Inputs")
left, right = st.columns(2)
with left:
    ui.line(ns, "wau", "Weekly active users", ",.0f")
    ui.line(ns, "completion_rate", "Completion rate", ".0%")
with right:
    ui.line(ns, "sessions_per_active_user", "Sessions started per active user", ".2f")
    ui.line(ns, "activation_rate", "Activation rate (first completion within 24 h)", ".0%")

st.markdown("##### Guardrails")
left, right = st.columns(2)
with left:
    ui.line(ns, "abandon_rate", "Abandon rate", ".0%")
with right:
    ui.line(ns, "load_ms_p75", "Page load time p75 (ms)", ",.0f")

st.markdown("##### Metric tree")
st.image(str(dd.DOCS_IMG / f"metric-tree-{ui.mode()}.png"))
st.caption(tables.label)
