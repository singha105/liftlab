import json

import numpy as np
import pandas as pd
import pytest

from liftlab import cli, cookie_cats, readout
from liftlab.stats.tests import welch_ttest, ztest_proportions

CONFIG = readout.load_config(cookie_cats.CONFIG)
LABEL = "REAL: Cookie Cats mobile game A/B test, public Kaggle data"


def _csv(path, n=(3000, 3000), d7=(0.19, 0.18), outlier=True, seed=0):
    """A file shaped like the Kaggle one, with exact 7-day retention rates."""
    rng = np.random.default_rng(seed)
    frames = []
    for arm, size, rate in zip(("gate_30", "gate_40"), n, d7, strict=True):
        frames.append(
            pd.DataFrame(
                {
                    "userid": np.arange(size) + (0 if arm == "gate_30" else 10**6),
                    "version": arm,
                    "sum_gamerounds": rng.negative_binomial(0.8, 0.015, size),
                    "retention_1": np.where(rng.uniform(size=size) < 0.45, "TRUE", "FALSE"),
                    "retention_7": np.where(np.arange(size) < round(rate * size), "TRUE", "FALSE"),
                }
            )
        )
    frame = pd.concat(frames, ignore_index=True)
    if outlier:
        frame.loc[0, "sum_gamerounds"] = 49_854
    frame.to_csv(path, index=False)
    return path


def test_config_is_the_preregistered_plan():
    assert CONFIG["primary"]["column"] == "retention_7"
    assert CONFIG["primary"]["mde"] == 0.01
    assert CONFIG["required_per_arm"] == 24641
    assert [m["column"] for m in CONFIG["secondary"]] == ["retention_1", "sum_gamerounds"]
    assert CONFIG["guardrails"][0]["max_increase"] == 0.01
    assert CONFIG["plausible_rounds_cap"] == 10_000
    assert [r["decision"] for r in CONFIG["decision_rule"]] == [
        "INVALID", "UNDERPOWERED", "KILL", "SHIP", "ITERATE", "KILL",
    ]  # fmt: skip
    assert CONFIG["actions"]["KILL"] == "keep the gate at level 30"


def test_load_maps_the_kaggle_columns(tmp_path):
    users = cookie_cats.load(_csv(tmp_path / "c.csv"))
    assert len(users) == 6000 and set(users.variant) == {"gate_30", "gate_40"}
    assert users.retention_7.dtype == bool and users.retention_1.dtype == bool
    assert (users.no_rounds == (users.sum_gamerounds == 0)).all()
    assert (users.source == "cookie_cats").all() and (users.variants == 1).all()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda f: f.drop(columns="retention_7"), "missing retention_7"),
        (lambda f: pd.concat([f, f.head(1)]), "more than once"),
        (lambda f: f.assign(retention_1="maybe"), "retention_1 must be true/false"),
    ],
)
def test_load_rejects_other_files(tmp_path, change, message):
    path = _csv(tmp_path / "c.csv")
    change(pd.read_csv(path)).to_csv(path, index=False)
    with pytest.raises(ValueError, match=message):
        cookie_cats.load(path)


def test_read_runs_the_plan_and_checks_outliers(tmp_path):
    users = cookie_cats.load(_csv(tmp_path / "c.csv", d7=(0.19, 0.25)))
    config = {**CONFIG, "required_per_arm": 2000}
    result = cookie_cats.read(users, config)
    r = result.readout
    assert r.label == f"{LABEL}, N = 6,000"
    assert r.decision == "SHIP" and r.action == "move the gate to level 40"
    assert r.primary.comparison == ztest_proportions(570, 3000, 750, 3000)
    assert [b.statistic for b in r.secondaries[1].bootstraps] == ["median"]

    o = result.outliers
    assert [(x.rounds, x.variant) for x in o.outliers] == [(49_854, "gate_30")]
    assert o.outliers[0].rounds_per_day == pytest.approx(49_854 / 14)
    assert o.largest_below_cap < 10_000
    assert o.with_all == r.secondaries[1].comparison  # the analysis of record keeps everyone
    kept = users[users.sum_gamerounds <= 10_000]
    assert o.without == welch_ttest(
        kept[kept.variant == "gate_30"].sum_gamerounds.astype(float),
        kept[kept.variant == "gate_40"].sum_gamerounds.astype(float),
    )

    markdown = result.to_markdown()
    assert markdown.count(f"{LABEL}, N = 6,000") == 2
    assert markdown.rstrip().endswith(f"*{LABEL}, N = 6,000*")
    assert "| 0 | gate_30 | 49,854 | 3,561 |" in markdown
    assert "## Why there's no CUPED" in markdown and "\n\n\n" not in markdown
    data = json.loads(result.to_json())
    assert data["outliers"]["outliers"][0]["rounds"] == 49_854


def test_underpowered_and_flat_data_keeps_the_gate(tmp_path):
    users = cookie_cats.load(_csv(tmp_path / "c.csv", d7=(0.19, 0.19), outlier=False))
    result = cookie_cats.read(users)
    assert result.readout.decision == "UNDERPOWERED"
    assert "underpowered (needs 24,641 per arm)" in result.readout.label
    assert result.outliers.outliers == ()
    flat = cookie_cats.read(users, {**CONFIG, "required_per_arm": 100}).readout
    assert (flat.decision, flat.action) == ("KILL", "keep the gate at level 30")


def test_cli_cookie_cats(tmp_path, capsys):
    missing = ["cookie-cats", "--path", str(tmp_path / "none.csv")]
    assert cli.main(missing) == 1
    assert cookie_cats.KAGGLE_URL in capsys.readouterr().err

    path = _csv(tmp_path / "c.csv")
    out = tmp_path / "exp-000.json"
    args = ["cookie-cats", "--path", str(path), "--format", "json", "--out", str(out)]
    assert cli.main([*args, "--charts", str(tmp_path / "img")]) == 0
    assert json.loads(out.read_text())["label"].startswith(LABEL)
    charts = sorted(p.name for p in (tmp_path / "img").glob("*.png"))
    assert charts == [
        "exp-000-gamerounds-dark.png", "exp-000-gamerounds-light.png",
        "exp-000-retention-dark.png", "exp-000-retention-light.png",
    ]  # fmt: skip


@pytest.mark.skipif(not cookie_cats.DEFAULT_CSV.exists(), reason="the Kaggle CSV isn't committed")
def test_the_real_file_matches_its_published_numbers():
    # The dataset's own description and every public analysis of it agree on these.
    users = cookie_cats.load(cookie_cats.DEFAULT_CSV)
    result = cookie_cats.read(users)
    r = result.readout
    assert r.users == {"gate_30": 44_700, "gate_40": 45_489}
    c = r.primary.comparison
    assert (round(c.control, 4), round(c.test, 4)) == (0.1902, 0.1820)
    assert c.p_value == pytest.approx(0.0016, abs=1e-4)
    assert r.srm.p_value == pytest.approx(0.0086, abs=1e-4) and not r.srm.mismatch
    one_day = r.secondaries[0].comparison
    assert (round(one_day.control, 4), round(one_day.test, 4)) == (0.4482, 0.4423)
    assert r.decision == "KILL"
    assert [x.rounds for x in result.outliers.outliers] == [49_854]
