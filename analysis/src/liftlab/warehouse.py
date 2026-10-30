"""The DuckDB warehouse: raw events in, SQL models out.

raw_events holds events from every source side by side, tagged `synthetic`, `posthog` or
`csv`. Loading a source replaces that source's rows and nothing else, and every model keeps
the `source` column, so real and synthetic numbers never mix.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

ANALYSIS_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = ANALYSIS_DIR.parent
SQL_DIR = ANALYSIS_DIR / "sql"
DEFAULT_DB = REPO_DIR / "data" / "warehouse.duckdb"
SOURCES = ("synthetic", "posthog", "csv")

SCHEMA = """
create table if not exists raw_events (
    source varchar not null,
    uuid varchar,
    event varchar not null,
    distinct_id varchar,
    timestamp timestamp not null,  -- UTC
    properties json,
    loaded_at timestamp not null
);
create table if not exists warehouse_meta (
    source varchar primary key,
    data_end timestamp not null,  -- events up to here are complete; periods after it aren't
    loaded_at timestamp not null,
    events bigint not null,
    note varchar
);
create table if not exists sim_truth (
    source varchar not null,
    metric varchar not null,
    value double not null
);
"""


@dataclass(frozen=True)
class Model:
    name: str
    path: Path


def connect(path: Path | str = DEFAULT_DB) -> duckdb.DuckDBPyConnection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute("set TimeZone = 'UTC'")
    con.execute(SCHEMA)
    return con


def load_events(
    con: duckdb.DuckDBPyConnection,
    events: pd.DataFrame,
    *,
    source: str,
    data_end: datetime,
    note: str = "",
) -> int:
    """Replace `source`'s rows in raw_events with `events` (PostHog export shape).

    `events` needs event, distinct_id, timestamp (UTC) and properties (JSON text or dicts);
    uuid is optional. Returns the number of rows loaded.
    """
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}")
    frame = events.copy()
    if "uuid" not in frame:
        frame["uuid"] = None
    frame["properties"] = [
        p if isinstance(p, str) or p is None else json.dumps(p) for p in frame["properties"]
    ]
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_localize(None)
    frame = frame[["uuid", "event", "distinct_id", "timestamp", "properties"]]
    loaded_at = datetime.now(UTC).replace(tzinfo=None)
    con.execute("begin")
    con.execute("delete from raw_events where source = ?", [source])
    con.register("incoming", frame)
    con.execute(
        """
        insert into raw_events
        select ?, uuid, event, distinct_id, timestamp, properties::json, ?
        from incoming
        """,
        [source, loaded_at],
    )
    con.unregister("incoming")
    con.execute(
        "insert or replace into warehouse_meta values (?, ?, ?, ?, ?)",
        [source, _naive_utc(data_end), loaded_at, len(frame), note],
    )
    con.execute("commit")
    return len(frame)


def save_truth(con: duckdb.DuckDBPyConnection, rows: list[tuple[str, float]]) -> None:
    con.execute("delete from sim_truth where source = 'synthetic'")
    con.executemany("insert into sim_truth values ('synthetic', ?, ?)", rows)


def models(sql_dir: Path = SQL_DIR) -> list[Model]:
    """SQL models in build order: files are numbered, and each creates the table it's named for."""
    return [Model(p.stem.split("_", 1)[1], p) for p in sorted(sql_dir.glob("[0-9][0-9]_*.sql"))]


def build(con: duckdb.DuckDBPyConnection, sql_dir: Path = SQL_DIR) -> list[str]:
    built = []
    for model in models(sql_dir):
        con.execute(model.path.read_text())
        built.append(model.name)
    return built


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
