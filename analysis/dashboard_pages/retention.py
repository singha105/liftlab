import streamlit as st

from liftlab import dashboard_ui as ui

st.title("Retention by cohort")
tables = ui.product_tables()
ui.badge(tables.label)
st.markdown(
    "Each row is the new users from one week. A cell is the share who started a session on "
    "day 1, 7 or 28 after their first open, on that day exactly. *not yet* means the cohort "
    "hadn't reached that day when the data ends."
)
ui.retention_heatmap(tables.retention)
st.caption(tables.label)
