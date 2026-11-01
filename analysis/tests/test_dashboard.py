"""The dashboard: its data layer against the library, the metric tree against METRICS.md, and
every page run headless with Streamlit's AppTest."""

import json

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from liftlab import dashboard_data as dd
from liftlab import metric_tree, readout, warehouse
from liftlab.stats import power as pw

DASHBOARD = str(warehouse.ANALYSIS_DIR / "dashboard.py")
PAGES = ("overview", "funnel", "retention", "experiments", "proofs")


@pytest.fixture(scope="module")
def tables():
    return dd.synthetic_tables()


def test_synthetic_tables_are_day_3s_run(tables):
    assert tables.label == readout.SYNTHETIC_LABEL and not tables.real
    assert list(tables.funnel["step"]) == list(dd.FUNNEL_STEPS)
    # Day 3's funnel: 5,069 of 16,881 new users activated.
    assert tables.funnel["users"].tolist()[0] == 16_881
    assert tables.funnel["users"].tolist()[2] == 5_069
    assert dd.biggest_drop(tables.funnel)["step"] == "session_started"
    week, value, previous = dd.latest_week(tables.north_star, "activation_rate")
    assert value == tables.north_star["activation_rate"].dropna().iloc[-1]
    assert previous == tables.north_star["activation_rate"].dropna().iloc[-2]


def test_no_real_data_means_no_real_tables_and_an_empty_interim(tmp_path):
    assert dd.real_tables(tmp_path / "none.duckdb") is None
    con = warehouse.connect(tmp_path / "w.duckdb")
    warehouse.build(con)
    con.close()
    assert dd.real_tables(tmp_path / "w.duckdb") is None
    interim = dd.exp_001_real(tmp_path / "w.duckdb")
    assert interim["users"] == {"control": 0, "test": 0}
    assert interim["label"].startswith("REAL: StudySprint live data, N = 0, underpowered")


def test_exp_000_falls_back_to_the_saved_readout(tmp_path):
    data = dd.exp_000(tmp_path / "none.csv")
    assert data["computed_from"] == "saved"
    assert data["decision"] == "KILL" and data["label"].startswith("REAL: Cookie Cats")
    assert data["outliers"]["outliers"][0]["rounds"] == 49_854


def test_exp_001_synthetic_is_day_5s_example():
    data = dd.exp_001_synthetic()
    assert data["label"] == readout.SYNTHETIC_LABEL
    assert data["decision"] == "SHIP"
    assert min(data["users"].values()) == 1377
    assert data["truth"]["activation_effect"] == 0.05
    assert data["primary"]["comparison"]["diff"] == pytest.approx(0.099, abs=0.001)


def test_metric_type_and_upload_readout():
    rng = np.random.default_rng(0)
    n = 4000
    frame = pd.DataFrame(
        {
            "arm": np.repeat(["a", "b"], n),
            "converted": np.where(rng.uniform(size=2 * n) < 0.3, "TRUE", "FALSE"),
            "clicks": rng.integers(0, 2, 2 * n),
            "revenue": rng.gamma(2.0, 5.0, 2 * n),
        }
    )
    assert dd.metric_type(frame["clicks"]) == "proportion"
    assert dd.metric_type(frame["revenue"]) == "mean"
    with pytest.raises(ValueError, match="aren't numbers"):
        dd.metric_type(pd.Series(["x", "1"], name="bad"))

    users = dd.upload_users(frame, "arm", ["converted", "revenue"])
    assert users["converted"].dtype == bool and users["revenue"].dtype == float
    config = dd.upload_config(
        users, control="a", treatment="b", primary="converted", secondaries=["revenue"], mde=0.05
    )
    baseline = users.loc[users.variant == "a", "converted"].mean()
    assert config["required_per_arm"] == pw.sample_size_proportions(baseline, 0.05)
    r = readout.build_readout(users, config)
    assert r.label == "REAL: uploaded CSV, N = 8,000"
    assert r.decision in ("SHIP", "ITERATE", "KILL")
    assert [b.statistic for b in r.secondaries[0].bootstraps] == ["median"]

    rows = dd.interval_rows(r.to_dict())
    primary = rows[rows.metric == "converted"]
    assert list(primary["method"]) == ["two-proportion z-test", "Bootstrap, mean"]
    assert primary["diff"].iloc[0] == pytest.approx(r.primary.comparison.diff * 100)


def test_sample_size_is_the_power_module():
    size = dd.sample_size(0.30, 0.05, alpha=0.05, power=0.80, daily=5)
    assert size == {"per_arm": 1377, "total": 2754, "days": 551}


def test_proof_captions_use_the_saved_numbers():
    numbers = dd.proof_numbers()
    captions = dd.proof_captions(numbers)
    assert set(captions) == {stem for stem, _ in dd.PROOFS}
    assert f"{numbers['aa']['rate']:.1%}" in captions["stats-aa-pvalues"]
    assert "27.3%" in captions["stats-peeking"] and "1.7%" in captions["stats-peeking"]
    for stem, _ in dd.PROOFS:
        assert (dd.DOCS_IMG / f"{stem}-light.png").exists()


def test_metric_tree_matches_metrics_md(tmp_path):
    tree = metric_tree.parse(metric_tree.METRICS.read_text())
    assert tree.root == "NSM" and tree.labels["NSM"] == ["Weekly completed sessions", "North Star"]
    assert len(tree.labels) == 15
    assert tree.guardrails == {"ABD", "LOAD"}
    assert ("NSM", "ABD", True) in tree.edges and ("NSM", "WAU", False) in tree.edges
    position = metric_tree.layout(tree)
    assert set(position) == set(tree.labels)
    leaves = [n for n in tree.labels if not any(p == n for p, _, _ in tree.edges)]
    assert len({position[n][0] for n in leaves}) == len(leaves)  # one column each
    # A parent sits over the middle of its solid children.
    assert position["SPU"][0] == (position["STICK"][0] + position["SUM"][0]) / 2
    assert position["NSM"][0] == (position["WAU"][0] + position["CR"][0]) / 2
    assert position["DRET"][1] == 3
    written = metric_tree.save(tree, tmp_path)
    assert sorted(p.name for p in written) == ["metric-tree-dark.png", "metric-tree-light.png"]
    with pytest.raises(ValueError, match="no mermaid"):
        metric_tree.parse("no diagram here")


def _page(name: str) -> AppTest:
    at = AppTest.from_file(DASHBOARD, default_timeout=180)
    return at.switch_page(f"dashboard_pages/{name}.py").run()


def _badges(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown if "-badge[" in m.value]


@pytest.mark.parametrize("name", PAGES)
def test_every_page_runs_and_shows_its_badge(name):
    at = _page(name)
    assert not at.exception
    assert _badges(at), f"{name} has no REAL or SYNTHETIC badge"
    assert all("[REAL]" in b or "[SYNTHETIC]" in b for b in _badges(at))


def test_experiments_page_shows_each_readout():
    at = _page("experiments")
    assert ":blue-badge[REAL]" in _badges(at)
    assert any("Decision: KILL: keep the gate at level 30" in m.value for m in at.markdown)
    assert [m.value for m in at.metric][-3:] == ["1,377", "2,754", "551"]

    at.segmented_control[0].set_value("EXP-001 Quick Start").run()
    assert not at.exception
    assert _badges(at) == [":blue-badge[REAL]", ":violet-badge[SYNTHETIC]"]
    assert any("Decision: SHIP" in m.value for m in at.markdown)

    at.segmented_control[0].set_value("Upload a CSV").run()
    assert not at.exception and len(at.get("file_uploader")) == 1

    at.number_input[0].set_value(19.0).run()
    at.number_input[1].set_value(1.0).run()
    assert at.metric[0].value == f"{pw.sample_size_proportions(0.19, 0.01):,}"


def test_saved_exp_000_matches_a_fresh_read():
    """The committed readout is what the CSV gives today (skipped where the CSV isn't)."""
    from liftlab import cookie_cats

    if not cookie_cats.DEFAULT_CSV.exists():
        pytest.skip("the Kaggle CSV isn't committed")
    saved = json.loads(dd.EXP_000_SAVED.read_text())
    fresh = json.loads(cookie_cats.read(cookie_cats.load(cookie_cats.DEFAULT_CSV)).to_json())
    assert fresh == saved
