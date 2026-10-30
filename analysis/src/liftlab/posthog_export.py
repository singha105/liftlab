"""Pull real StudySprint events out of PostHog through the query API.

POST {app host}/api/projects/{project_id}/query/ with a HogQL query, using a personal API key
with the query:read scope. PostHog returns at most 50,000 rows per query and rejects OFFSET
for personal keys, so pages are keyset-paginated on timestamp, and rows that share the
boundary timestamp are de-duplicated by uuid. The key comes from .env and is only ever put in
the Authorization header: it's never printed, logged or written anywhere.

Output is one JSON object per line in data/raw/ (gitignored), plus a small .meta.json saying
which time range it covers, so the loader knows where the data ends.
"""

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

PLANNED_EVENTS = (
    "app_opened",
    "session_started",
    "session_completed",
    "session_abandoned",
    "streak_viewed",
    "weekly_summary_viewed",
    "experiment_exposed",
)
INGESTION_TO_APP = {
    "https://us.i.posthog.com": "https://us.posthog.com",
    "https://eu.i.posthog.com": "https://eu.posthog.com",
}
DEFAULT_HOST = "https://us.posthog.com"
PAGE_SIZE = 10_000

Post = Callable[[str, dict, str], dict]


class ExportError(RuntimeError):
    pass


def read_env(path: Path) -> dict[str, str]:
    """KEY=VALUE pairs from a .env file, with the process environment filling any gaps."""
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("'\"")
    for key in ("POSTHOG_HOST", "POSTHOG_PROJECT_ID", "POSTHOG_PERSONAL_API_KEY"):
        if not values.get(key) and os.environ.get(key):
            values[key] = os.environ[key]
    return values


def app_host(host: str | None) -> str:
    """The private API lives on the app host, not the ingestion host the front end uses."""
    host = (host or DEFAULT_HOST).rstrip("/")
    return INGESTION_TO_APP.get(host, host)


def page_query(after: datetime, until: datetime, page_size: int = PAGE_SIZE) -> str:
    events = ", ".join(f"'{name}'" for name in PLANNED_EVENTS)
    return (
        "select uuid, event, distinct_id, timestamp, properties from events "
        f"where event in ({events}) "
        f"and timestamp >= '{_hogql_time(after)}' and timestamp < '{_hogql_time(until)}' "
        f"order by timestamp limit {page_size}"
    )


def export_events(
    *,
    host: str | None,
    project_id: str,
    api_key: str,
    since: datetime,
    until: datetime,
    out: Path,
    page_size: int = PAGE_SIZE,
    post: Post | None = None,
) -> int:
    """Write every planned event in [since, until) to `out`; return how many."""
    post = post or _post
    url = f"{app_host(host)}/api/projects/{project_id}/query/"
    out.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    cursor = since
    written = 0
    with out.open("w") as file:
        while True:
            body = {
                "query": {"kind": "HogQLQuery", "query": page_query(cursor, until, page_size)},
                "name": "liftlab export",
            }
            response = post(url, body, api_key)
            columns = response.get("columns") or [
                "uuid",
                "event",
                "distinct_id",
                "timestamp",
                "properties",
            ]
            rows = [dict(zip(columns, row, strict=True)) for row in response.get("results", [])]
            fresh = [row for row in rows if str(row["uuid"]) not in seen]
            for row in fresh:
                seen.add(str(row["uuid"]))
                properties = row["properties"]
                if isinstance(properties, str):
                    properties = json.loads(properties)
                file.write(
                    json.dumps(
                        {
                            "uuid": str(row["uuid"]),
                            "event": row["event"],
                            "distinct_id": row["distinct_id"],
                            "timestamp": row["timestamp"],
                            "properties": properties,
                        }
                    )
                    + "\n"
                )
            written += len(fresh)
            if len(rows) < page_size:
                break
            last = _parse_time(rows[-1]["timestamp"])
            if last <= cursor and not fresh:
                raise ExportError(
                    f"more than {page_size} events share one timestamp; raise the page size"
                )
            cursor = last
    meta = {"since": since.isoformat(), "until": until.isoformat(), "events": written}
    out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return written


def _post(url: str, body: dict, api_key: str) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:300]
        raise ExportError(f"PostHog returned HTTP {error.code}: {detail}") from None
    except urllib.error.URLError as error:
        raise ExportError(f"couldn't reach PostHog: {error.reason}") from None


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _hogql_time(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")
