import json

import pandas as pd

from liftlab import cli, warehouse


def test_load_build_report_on_synthetic_data(tmp_path, capsys):
    db = tmp_path / "warehouse.duckdb"
    assert cli.main(["--db", str(db), "load", "--source", "synthetic", "--users", "1500"]) == 0
    assert cli.main(["--db", str(db), "build"]) == 0
    assert cli.main(["--db", str(db), "report"]) == 0
    out = capsys.readouterr().out
    assert out.count("SYNTHETIC") == 2  # labelled above and below the tables
    assert "second_session_7d" in out
    con = warehouse.connect(db)
    assert con.execute(
        "select count(*) from sim_truth where metric = 'activation_rate'"
    ).fetchone() == (1,)


def test_loading_a_source_replaces_only_that_source(tmp_path):
    db = tmp_path / "warehouse.duckdb"
    csv = tmp_path / "export.csv"
    pd.DataFrame(
        {
            "event": ["app_opened"],
            "distinct_id": ["real-user"],
            "timestamp": ["2026-10-29T10:00:00-04:00"],
            "properties": [json.dumps({"is_first_open": True})],
        }
    ).to_csv(csv, index=False)
    assert cli.main(["--db", str(db), "load", "--source", "synthetic", "--users", "300"]) == 0
    assert cli.main(["--db", str(db), "load", "--source", "csv", "--path", str(csv)]) == 0
    assert cli.main(["--db", str(db), "load", "--source", "csv", "--path", str(csv)]) == 0
    con = warehouse.connect(db)
    counts = dict(con.execute("select source, count(*) from raw_events group by 1").fetchall())
    assert counts["csv"] == 1
    assert counts["synthetic"] > 1000
    stamp = con.execute("select timestamp::varchar from raw_events where source = 'csv'").fetchone()
    assert stamp == ("2026-10-29 14:00:00",)  # stored in UTC


def test_power_prints_the_plan(capsys):
    assert cli.main(["power", "--baseline", "0.30", "--mde", "0.05", "--daily", "10"]) == 0
    out = capsys.readouterr().out
    assert "MDE +5.0pp absolute (+16.7% relative)" in out
    assert "Required: 1,377 users per arm (2,754 total)" in out
    assert "at 10 new users/day: 276 days" in out
    assert cli.main(["power", "--baseline", "0.30", "--n", "1377"]) == 0
    assert "MDE +5.0pp" in capsys.readouterr().out
    assert cli.main(["power", "--baseline", "0.30"]) == 1
