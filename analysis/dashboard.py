"""The LiftLab dashboard. From the repo root, so Streamlit finds .streamlit/config.toml:
`uv run --project analysis streamlit run analysis/dashboard.py`."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
try:
    import liftlab  # noqa: F401
except ModuleNotFoundError:  # `uv sync` installs the package; pip installing the deps doesn't
    sys.path.insert(0, str(HERE / "src"))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="LiftLab", page_icon=":material/experiment:", layout="wide")

pages = st.navigation(
    [
        st.Page(HERE / "dashboard_pages" / "overview.py", title="Overview",
                icon=":material/monitoring:", default=True),
        st.Page(HERE / "dashboard_pages" / "funnel.py", title="Funnel",
                icon=":material/filter_alt:"),
        st.Page(HERE / "dashboard_pages" / "retention.py", title="Retention",
                icon=":material/grid_on:"),
        st.Page(HERE / "dashboard_pages" / "experiments.py", title="Experiments",
                icon=":material/science:"),
        st.Page(HERE / "dashboard_pages" / "proofs.py", title="Stats proofs",
                icon=":material/fact_check:"),
    ]
)  # fmt: skip
st.sidebar.caption(
    "LiftLab: product analytics and experiment statistics for StudySprint, a focus timer. "
    "Every number is labeled REAL or SYNTHETIC. "
    "[Source on GitHub](https://github.com/singha105/liftlab)"
)
pages.run()
