import streamlit as st

from liftlab import dashboard_data as dd
from liftlab import dashboard_ui as ui
from liftlab.readout import SYNTHETIC_LABEL

st.title("Stats proofs")
ui.badge(SYNTHETIC_LABEL)
st.markdown(
    "Before the stats library read any real experiment, it was run on thousands of simulated "
    "ones where the true answer is known. Each chart is one check, from `liftlab proofs`; "
    "the methods are explained in "
    "[STATS.md](https://github.com/singha105/liftlab/blob/main/docs/STATS.md)."
)
captions = dd.proof_captions(dd.proof_numbers())
for stem, title in dd.PROOFS:
    st.markdown(f"##### {title}")
    st.image(str(dd.DOCS_IMG / f"{stem}-{ui.mode()}.png"))
    st.caption(captions[stem])
st.caption(SYNTHETIC_LABEL)
