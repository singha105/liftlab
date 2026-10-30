import json
from datetime import UTC, datetime

import pytest

from liftlab import cli, posthog_export
from liftlab.posthog_export import app_host, export_events, page_query, read_env

KEY = "phx_not_a_real_key_0123456789"


def row(n: int, ts: str) -> list:
    return [f"uuid-{n}", "app_opened", f"user-{n}", ts, json.dumps({"load_ms": n})]


def test_reads_keys_from_dotenv_with_environment_fallback(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# PostHog\nPOSTHOG_PROJECT_ID='12345'\nPOSTHOG_PERSONAL_API_KEY=\n")
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", KEY)
    values = read_env(env)
    assert values["POSTHOG_PROJECT_ID"] == "12345"
    assert values["POSTHOG_PERSONAL_API_KEY"] == KEY


def test_private_api_uses_the_app_host():
    assert app_host("https://us.i.posthog.com") == "https://us.posthog.com"
    assert app_host("https://eu.i.posthog.com/") == "https://eu.posthog.com"
    assert app_host("") == "https://us.posthog.com"


def test_query_selects_only_planned_events_without_offset():
    query = page_query(datetime(2026, 10, 29, tzinfo=UTC), datetime(2026, 10, 30, tzinfo=UTC), 500)
    assert "event in ('app_opened', 'session_started'" in query
    assert "order by timestamp limit 500" in query
    assert "offset" not in query.lower()


def test_keyset_pages_without_losing_or_repeating_events(tmp_path):
    pages = [
        [
            row(1, "2026-10-29T10:00:00Z"),
            row(2, "2026-10-29T11:00:00Z"),
            row(3, "2026-10-29T11:00:00Z"),
        ],
        [
            row(2, "2026-10-29T11:00:00Z"),
            row(3, "2026-10-29T11:00:00Z"),
            row(4, "2026-10-29T11:00:00Z"),
        ],
        [row(4, "2026-10-29T11:00:00Z"), row(5, "2026-10-29T12:00:00Z")],
    ]
    calls = []

    def fake_post(url, body, api_key):
        calls.append((url, body["query"]["query"], api_key))
        return {
            "columns": ["uuid", "event", "distinct_id", "timestamp", "properties"],
            "results": pages[len(calls) - 1],
        }

    out = tmp_path / "events.jsonl"
    count = export_events(
        host="https://us.i.posthog.com",
        project_id="12345",
        api_key=KEY,
        since=datetime(2026, 10, 29, tzinfo=UTC),
        until=datetime(2026, 10, 30, tzinfo=UTC),
        out=out,
        page_size=3,
        post=fake_post,
    )
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert count == 5
    assert [line["uuid"] for line in lines] == [f"uuid-{n}" for n in range(1, 6)]
    assert lines[0]["properties"] == {"load_ms": 1}
    assert calls[0][0] == "https://us.posthog.com/api/projects/12345/query/"
    assert "timestamp >= '2026-10-29 11:00:00.000000'" in calls[1][1]
    meta = json.loads(out.with_suffix(".meta.json").read_text())
    assert meta["events"] == 5
    for written in (out, out.with_suffix(".meta.json")):
        assert KEY not in written.read_text()


def test_stops_if_one_timestamp_fills_a_page(tmp_path):
    same = [row(n, "2026-10-29T10:00:00Z") for n in range(3)]

    def fake_post(url, body, api_key):
        return {"results": same}

    with pytest.raises(posthog_export.ExportError, match="share one timestamp"):
        export_events(
            host=None,
            project_id="1",
            api_key=KEY,
            since=datetime(2026, 10, 29, tzinfo=UTC),
            until=datetime(2026, 10, 30, tzinfo=UTC),
            out=tmp_path / "x.jsonl",
            page_size=3,
            post=fake_post,
        )


def test_cli_skips_cleanly_without_a_key(monkeypatch, capsys):
    monkeypatch.setattr(posthog_export, "read_env", lambda path: {})
    assert cli.main(["export-posthog"]) == 1
    assert "not set in .env" in capsys.readouterr().err
