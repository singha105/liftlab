"""`liftlab`: load events into the warehouse, build the SQL models, print the reports."""

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from liftlab import posthog_export, warehouse
from liftlab.simulate import Experiment, simulate

POSTHOG_EXPORT = warehouse.REPO_DIR / "data" / "raw" / "posthog_events.jsonl"
SYNTHETIC_LABEL = "SYNTHETIC: simulated users with known ground truth, not real usage"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="liftlab", description=__doc__)
    parser.add_argument("--db", type=Path, default=warehouse.DEFAULT_DB, help="DuckDB file")
    commands = parser.add_subparsers(dest="command", required=True)

    load = commands.add_parser("load", help="load events into raw_events")
    load.add_argument("--source", choices=warehouse.SOURCES, required=True)
    load.add_argument("--path", type=Path, help="file to load (posthog: JSONL, csv: CSV)")
    load.add_argument("--data-end", help="csv only: when the export ends (ISO time, UTC)")
    load.add_argument("--users", type=int, default=20_000, help="synthetic only")
    load.add_argument("--seed", type=int, default=7, help="synthetic only")
    load.add_argument("--weeks", type=int, default=8, help="synthetic only")
    load.add_argument("--experiment", help="synthetic only: run an experiment with this key")
    load.add_argument("--experiment-start-day", type=int, default=28)
    load.add_argument("--audience", choices=("all", "new"), default="all")
    load.add_argument("--activation-effect", type=float, default=0.0)
    load.add_argument("--sessions-effect", type=float, default=0.0)
    load.add_argument("--srm-loss", type=float, default=0.0)

    commands.add_parser("build", help="build the SQL models in analysis/sql/")
    report = commands.add_parser("report", help="print the funnel, retention and North Star")
    report.add_argument("--source", choices=warehouse.SOURCES, default="synthetic")

    export = commands.add_parser("export-posthog", help="pull real events from PostHog")
    export.add_argument("--since", default="2026-10-29", help="start date (UTC)")
    export.add_argument("--out", type=Path, default=POSTHOG_EXPORT)

    args = parser.parse_args(argv)
    if args.command == "export-posthog":
        return _export(args)
    con = warehouse.connect(args.db)
    if args.command == "load":
        return _load(con, args)
    if args.command == "build":
        started = time.perf_counter()
        built = warehouse.build(con)
        print(f"built {', '.join(built)} in {time.perf_counter() - started:.1f}s")
        return 0
    return _report(con, args.source)


def _load(con, args) -> int:
    if args.source == "synthetic":
        experiment = None
        if args.experiment:
            experiment = Experiment(
                key=args.experiment,
                start_day=args.experiment_start_day,
                audience=args.audience,
                activation_effect=args.activation_effect,
                sessions_effect=args.sessions_effect,
                srm_loss=args.srm_loss,
            )
        started = time.perf_counter()
        sim = simulate(args.users, seed=args.seed, weeks=args.weeks, experiment=experiment)
        elapsed = time.perf_counter() - started
        note = f"simulate(n_users={args.users}, seed={args.seed}, weeks={args.weeks})"
        if experiment:
            note += f", {experiment}"
        rows = warehouse.load_events(
            con, sim.events, source="synthetic", data_end=sim.truth.data_end, note=note
        )
        warehouse.save_truth(con, sim.truth.as_rows())
        print(f"simulated {args.users:,} users in {elapsed:.1f}s; loaded {rows:,} synthetic events")
        print(
            f"true activation rate {sim.truth.activation_rate:.4f}, "
            f"true D7 retention {sim.truth.retention_curve[7]:.4f}"
        )
        return 0

    if args.source == "posthog":
        path = args.path or POSTHOG_EXPORT
        if not path.exists():
            print(f"no export at {path}; run `liftlab export-posthog` first", file=sys.stderr)
            return 1
        meta = json.loads(path.with_suffix(".meta.json").read_text())
        events = pd.read_json(path, lines=True, dtype={"uuid": str, "distinct_id": str})
        data_end = datetime.fromisoformat(meta["until"])
    else:
        if not args.path:
            print("--path is required for --source csv", file=sys.stderr)
            return 1
        events = pd.read_csv(args.path, dtype=str)
        stamps = pd.to_datetime(events["timestamp"], utc=True)
        data_end = datetime.fromisoformat(args.data_end) if args.data_end else stamps.max()
    rows = warehouse.load_events(con, events, source=args.source, data_end=data_end)
    print(f"loaded {rows:,} {args.source} events")
    return 0


def _report(con, source: str) -> int:
    meta = con.execute(
        "select data_end, note from warehouse_meta where source = ?", [source]
    ).fetchone()
    if meta is None:
        print(f"no {source} data loaded", file=sys.stderr)
        return 1
    print(SYNTHETIC_LABEL if source == "synthetic" else f"SOURCE: {source}")
    print(f"data through {meta[0]:%Y-%m-%d %H:%M} UTC  {meta[1] or ''}".rstrip())

    print("\nActivation funnel (new users with 7 full days of data)")
    print(f"  {'step':<20}{'users':>9}{'step_conv':>11}{'overall':>9}{'drop_off':>10}")
    for _, step, users, step_conv, overall, drop in con.execute(
        "select step_number, step, users, step_conversion, overall_conversion, drop_off "
        "from funnel_activation where source = ? order by step_number",
        [source],
    ).fetchall():
        print(f"  {step:<20}{users:>9,}{step_conv:>11.1%}{overall:>9.1%}{drop:>10,}")

    print("\nRetention by weekly cohort (session started on day n exactly)")
    print(f"  {'cohort_week':<13}{'users':>7}{'D1':>8}{'D7':>8}{'D28':>8}")
    for week, users, d1, d7, d28 in con.execute(
        "select cohort_week, cohort_users, d1_retention, d7_retention, d28_retention "
        "from retention_cohorts where source = ? order by cohort_week",
        [source],
    ).fetchall():
        print(f"  {week!s:<13}{users:>7,}{_pct(d1):>8}{_pct(d7):>8}{_pct(d28):>8}")

    print("\nNorth Star by week")
    print(
        f"  {'week':<13}{'WCS':>8}{'WAU':>7}{'sess/WAU':>10}{'compl.':>8}{'activ.':>8}"
        f"{'abandon':>9}{'p75 ms':>8}"
    )
    for row in con.execute(
        "select week_start, weekly_completed_sessions, wau, sessions_per_active_user, "
        "completion_rate, activation_rate, abandon_rate, load_ms_p75 "
        "from north_star_weekly where source = ? order by week_start",
        [source],
    ).fetchall():
        week, wcs, wau, spu, cr, act, abandon, p75 = row
        print(
            f"  {week!s:<13}{wcs:>8,}{wau:>7,}{spu or 0:>10.2f}{_pct(cr):>8}{_pct(act):>8}"
            f"{_pct(abandon):>9}{p75 or 0:>8.0f}"
        )
    if source == "synthetic":
        print(f"\n{SYNTHETIC_LABEL}")
    return 0


def _export(args) -> int:
    env = posthog_export.read_env(warehouse.REPO_DIR / ".env")
    missing = [k for k in ("POSTHOG_PROJECT_ID", "POSTHOG_PERSONAL_API_KEY") if not env.get(k)]
    if missing:
        print(
            f"skipping the PostHog export: {' and '.join(missing)} not set in .env", file=sys.stderr
        )
        return 1
    since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
    until = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=5)
    try:
        count = posthog_export.export_events(
            host=env.get("POSTHOG_HOST"),
            project_id=env["POSTHOG_PROJECT_ID"],
            api_key=env["POSTHOG_PERSONAL_API_KEY"],
            since=since,
            until=until,
            out=args.out,
        )
    except posthog_export.ExportError as error:
        print(f"export failed: {error}", file=sys.stderr)
        return 1
    print(f"exported {count:,} events to {args.out}")
    return 0


def _pct(value) -> str:
    return "-" if value is None or value != value else f"{value:.1%}"


if __name__ == "__main__":
    raise SystemExit(main())
