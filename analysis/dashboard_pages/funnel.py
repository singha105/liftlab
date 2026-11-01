import streamlit as st

from liftlab import dashboard_data as dd
from liftlab import dashboard_ui as ui

st.title("Activation funnel")
tables = ui.product_tables()
ui.badge(tables.label)
funnel = tables.funnel
worst = dd.biggest_drop(funnel)
before = funnel.loc[funnel["step_number"] == worst["step_number"] - 1, "users"].iloc[0]
st.markdown(
    "New users whose first 7 days are fully in the data, and how far each got. The orange bar "
    "is the step that loses the most people."
)
with st.container(border=True):
    st.markdown(
        f"**Biggest drop-off: {dd.FUNNEL_STEPS[worst['step']].lower()}.** "
        f"{worst['drop_off']:,} of {before:,} new users ({worst['drop_off'] / before:.0%}) "
        "never got there. EXP-001's Quick Start targets this step."
    )
ui.funnel(funnel)
st.dataframe(
    funnel.assign(step=funnel["step"].map(dd.FUNNEL_STEPS))[
        ["step", "users", "step_conversion", "overall_conversion", "drop_off"]
    ],
    hide_index=True,
    width="stretch",
    column_config={
        "step": "Step",
        "users": st.column_config.NumberColumn("Users", format="localized"),
        "step_conversion": st.column_config.NumberColumn("From the step before", format="percent"),
        "overall_conversion": st.column_config.NumberColumn("Of everyone", format="percent"),
        "drop_off": st.column_config.NumberColumn("Lost at this step", format="localized"),
    },
)
st.caption(tables.label)
