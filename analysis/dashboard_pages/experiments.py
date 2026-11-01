import pandas as pd
import streamlit as st

from liftlab import dashboard_data as dd
from liftlab import dashboard_ui as ui
from liftlab import readout

st.title("Experiments")
choice = st.segmented_control(
    "Experiment",
    ["EXP-000 Cookie Cats", "EXP-001 Quick Start", "Upload a CSV"],
    default="EXP-000 Cookie Cats",
)

if choice == "EXP-000 Cookie Cats":
    st.markdown(
        "A public A/B test from the mobile game Cookie Cats: did moving the first gate from "
        "level 30 to level 40 change 7-day retention? Re-analyzed with the plan in "
        "[EXP-000](https://github.com/singha105/liftlab/blob/main/docs/experiments/"
        "EXP-000-cookie-cats.md); the decision memo is "
        "[EXP-000-memo.md](https://github.com/singha105/liftlab/blob/main/docs/experiments/"
        "EXP-000-memo.md)."
    )
    upload = None
    if not dd.cookie_cats.DEFAULT_CSV.exists():
        upload = st.file_uploader(
            "cookie_cats.csv from Kaggle, to recompute everything here (optional)", type="csv"
        )
    data = ui.exp_000(upload.getvalue() if upload else None)
    if data["computed_from"] == "saved":
        st.info(
            "Showing the saved readout. Upload cookie_cats.csv "
            f"([Kaggle]({dd.cookie_cats.KAGGLE_URL})) to recompute it from the players."
        )
    ui.readout(data)
    o = data["outliers"]
    st.markdown(f"##### Outliers: game rounds over {o['cap']:,}")
    st.markdown(
        f"Nobody is dropped from the analysis of record. The 99.9th percentile is "
        f"{o['p999']:,.0f} rounds and the largest total under the cap is "
        f"{o['largest_below_cap']:,}."
    )
    st.dataframe(
        pd.DataFrame(o["outliers"]),
        hide_index=True,
        width="stretch",
        column_config={
            "user_id": st.column_config.NumberColumn("Player", format="plain"),
            "variant": "Arm",
            "rounds": st.column_config.NumberColumn("Rounds in 14 days", format="localized"),
            "rounds_per_day": st.column_config.NumberColumn("Per day", format="%.0f"),
            "retention_1": "Back on day 1",
            "retention_7": "Back on day 7",
        },
    )
    a, b = o["with_all"], o["without"]
    st.markdown(
        f"Game rounds, Welch's t: everyone {a['diff']:+.2f} (p = {a['p_value']:.2f}); without "
        f"the players over the cap {b['diff']:+.2f} (p = {b['p_value']:.2f}), a sensitivity "
        "check that decides nothing. CUPED isn't used: players were randomized at install, so "
        "there's no pre-experiment behavior to adjust with."
    )

elif choice == "EXP-001 Quick Start":
    st.markdown(
        'StudySprint\'s own test: a one-click "Start a 25-minute focus" for new users, '
        "against the current start screen. Primary metric: activation rate. "
        "[Pre-registration](https://github.com/singha105/liftlab/blob/main/docs/experiments/"
        "EXP-001.md)."
    )
    real_tab, synthetic_tab = st.tabs(["REAL: live data", "SYNTHETIC: full-size simulation"])
    with real_tab:
        st.markdown("#### Interim read, not a decision")
        ui.interim(ui.exp_001_real())
    with synthetic_tab:
        data = ui.exp_001_synthetic()
        truth = data["truth"]
        st.markdown(
            f"One simulated run at the planned N, with a true activation effect of "
            f"**{truth['activation_effect'] * 100:+.1f} points** on a true control rate of "
            f"{truth['control_activation']:.1%}. It checks the method end to end; it says "
            "nothing about how well Quick Start works."
        )
        ui.readout(data)

else:
    st.markdown(
        "Any CSV with one row per user: a column naming the arm and one or more metric "
        "columns, true/false or 0/1 for a rate, numbers for a mean. It runs the same rule "
        "order as EXP-000 and EXP-001. The required N comes from the control arm itself, so it "
        "says whether this file could detect the MDE, not what a plan would have said."
    )
    upload = st.file_uploader("CSV file", type="csv", key="any_csv")
    if upload:
        frame = pd.read_csv(upload)
        with st.form("upload_readout"):
            variant = st.selectbox("Arm column", frame.columns)
            arms = sorted(frame[variant].astype(str).unique())
            left, right = st.columns(2)
            control = left.selectbox("Control arm", arms, index=0)
            treatment = right.selectbox("Test arm", arms, index=min(1, len(arms) - 1))
            others = [c for c in frame.columns if c != variant]
            primary = st.selectbox("Primary metric", others)
            secondaries = st.multiselect("Secondary metrics (Holm-corrected)", others)
            left, right = st.columns(2)
            mde = left.number_input(
                "MDE, absolute (0.01 = 1 point for a rate)", value=0.01, min_value=1e-6,
                format="%.4f",
            )  # fmt: skip
            share = right.number_input("Planned control share", 0.05, 0.95, 0.5, 0.05)
            submitted = st.form_submit_button("Run the readout")
        if submitted:
            try:
                if control == treatment:
                    raise ValueError("pick two different arms")
                metrics = [primary, *[s for s in secondaries if s != primary]]
                users = dd.upload_users(frame, variant, metrics)
                users = users[users["variant"].isin([control, treatment])]
                config = dd.upload_config(
                    users, control=control, treatment=treatment, primary=primary,
                    secondaries=metrics[1:], mde=mde, control_share=share,
                )  # fmt: skip
                ui.readout(readout.build_readout(users, config).to_dict())
            except ValueError as error:
                st.error(f"Can't read this file that way: {error}")

st.divider()
st.markdown("### Sample-size calculator")
st.markdown(
    "Users per arm for a two-sided test of two rates, and how long that takes at your "
    "traffic. The same math as `liftlab power`."
)
cols = st.columns(5)
baseline = cols[0].number_input("Baseline rate (%)", 0.1, 99.9, 30.0, 0.5) / 100
mde_pp = cols[1].number_input("MDE (points)", 0.05, 50.0, 5.0, 0.25)
alpha = cols[2].number_input("Alpha", 0.001, 0.2, 0.05, 0.01, format="%.3f")
power = cols[3].number_input("Power", 0.5, 0.99, 0.80, 0.05)
daily = cols[4].number_input("Eligible users a day", 1.0, 1e7, 5.0, 1.0)
try:
    size = dd.sample_size(baseline, mde_pp / 100, alpha=alpha, power=power, daily=daily)
    out = st.columns(3)
    out[0].metric("Users per arm", f"{size['per_arm']:,}")
    out[1].metric("Users in total", f"{size['total']:,}")
    out[2].metric("Days at that traffic", f"{size['days']:,}")
except ValueError as error:
    st.error(str(error))
